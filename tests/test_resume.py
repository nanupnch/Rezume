"""Compile real PDFs to catch clipped text, broken links, and font-size leaks."""

import os
from pathlib import Path
import re
import subprocess
import unicodedata
import unittest
from urllib.parse import urlparse

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.environ.get("REZUME_ENGINE", "pdflatex")
BUILD_DIR = Path(os.environ.get("REZUME_BUILD_DIR", ROOT / "build" / ENGINE))
ENGINE_FLAGS = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def links(reader):
    return {
        str(action["/URI"])
        for page in reader.pages
        for ref in page.get("/Annots", [])
        for action in [ref.get_object().get("/A", {})]
        if action.get("/S") == "/URI"
    }


class ResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "rezume.tex").read_text()
        cls.sample = PdfReader(BUILD_DIR / "rezume.pdf")

    def compile_case(self, name, source):
        directory = BUILD_DIR / "checks" / name
        directory.mkdir(parents=True, exist_ok=True)
        tex = directory / "resume.tex"
        tex.write_text(source)
        command = [
            "latexmk", ENGINE_FLAGS[ENGINE], "-interaction=nonstopmode",
            "-halt-on-error", "-file-line-error", "-outdir=" + str(directory), str(tex),
        ]
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120)
        (directory / "command.log").write_text(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)
        return PdfReader(directory / "resume.pdf"), (directory / "resume.log").read_text()

    def assert_clean_log(self, log):
        self.assertNotRegex(log, r"Overfull|Underfull|Missing character|LaTeX Warning|Package \S+ Warning")

    def test_sample_is_one_readable_a4_page(self):
        self.assertEqual(len(self.sample.pages), 1)
        page = self.sample.pages[0]
        self.assertAlmostEqual(float(page.mediabox.width), 595.276, places=1)
        self.assertAlmostEqual(float(page.mediabox.height), 841.89, places=1)
        text = compact(page.extract_text())
        for expected in ("Jane Doe", "Full Stack Developer", "Technical Skills", "Experience",
                         "Education", "Projects", "Certifications", "5555555555"):
            with self.subTest(expected=expected):
                self.assertIn(compact(expected), text)
        self.assert_clean_log((BUILD_DIR / "rezume.log").read_text())

    def test_fonts_are_embedded_and_have_unicode_mappings(self):
        names = set()
        for ref in self.sample.pages[0]["/Resources"]["/Font"].values():
            font = ref.get_object()
            names.add(str(font["/BaseFont"]))
            self.assertIn("/ToUnicode", font)
            descendants = font.get("/DescendantFonts", [font])
            for descendant in descendants:
                descriptor = descendant.get_object()["/FontDescriptor"]
                self.assertTrue(any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")))
        self.assertTrue(any("SourceSansPro" in name for name in names), names)

    def test_hyperlinks_preserve_complete_valid_destinations(self):
        expected = set(re.findall(r"\\href\{([^}]+)\}", self.source))
        self.assertEqual(links(self.sample), expected)
        for target in expected:
            parsed = urlparse(target)
            with self.subTest(target=target):
                self.assertIn(parsed.scheme, ("https", "mailto"))
                if parsed.scheme == "https":
                    self.assertTrue(parsed.netloc, target)
        project_sources = {urlparse(target).netloc for target in expected if "/source-code/" in target}
        self.assertEqual(project_sources, {"project1.com", "project2.com"})

    def test_long_contact_details_remain_readable(self):
        name = "Alexandra Catherine Montgomery"
        email = "alexandra.catherine.montgomery@engineering.example.com"
        location = "Greater Los Angeles Metropolitan Area, California, United States"
        cases = {
            "long-name": {"Jane Doe": name},
            "long-email": {"jane.doe@anymail.com": email},
            "long-location": {"Location: Anycity, Anystate, Anycountry": "Location: " + location},
            "combined": {"Jane Doe": name, "jane.doe@anymail.com": email,
                         "Location: Anycity, Anystate, Anycountry": "Location: " + location},
        }
        sample_body = compact(self.sample.pages[0].extract_text()).split("fullstackdeveloper", 1)[1]
        for case, replacements in cases.items():
            with self.subTest(case=case):
                source = self.source
                for before, after in replacements.items():
                    source = source.replace(before, after)
                reader, log = self.compile_case(case, source)
                self.assert_clean_log(log)
                self.assertEqual(len(reader.pages), 1)
                text = compact(reader.pages[0].extract_text())
                for value in replacements.values():
                    self.assertIn(compact(value), text)
                self.assertEqual(text.split("fullstackdeveloper", 1)[1], sample_body)
                expected_links = set(re.findall(r"\\href\{([^}]+)\}", source))
                self.assertEqual(links(reader), expected_links)

    def test_summary_font_size_does_not_leak(self):
        before = r"\makeatletter\typeout{REVIEW-BEFORE=\f@size}\makeatother" + "\n"
        after = r"\makeatletter\typeout{REVIEW-AFTER=\f@size}\makeatother" + "\n"
        source = self.source.replace(r"\section{Full Stack Developer}", before + r"\section{Full Stack Developer}")
        source = source.replace(r"\section{Technical Skills}", after + r"\section{Technical Skills}")
        _, log = self.compile_case("summary-font-scope", source)
        sizes = re.findall(r"REVIEW-(?:BEFORE|AFTER)=([\d.]+)", log)
        self.assertEqual(len(sizes), 2)
        self.assertEqual(sizes[0], sizes[1])

    def test_long_headings_remain_readable(self):
        cases = {
            "long-project-heading": {
                r"\uline{Project 1}": r"\uline{Distributed Event Processing and Observability Platform}",
                "React.js, Redux, PHP, MySQL, Git":
                    "TypeScript, React, Next.js, Node.js, PostgreSQL, Redis, Docker, "
                    "Kubernetes, AWS, Terraform, GitHub Actions",
                r"\uline{Source Code}": r"\uline{Repository and Architecture Documentation}",
            },
            "long-experience-heading": {
                "{Web Developer}{Apr 2022 -- Present}":
                    "{Senior Software Engineer, Developer Experience and Platform Infrastructure}"
                    "{September 2022 -- Present}",
                "{Anycompany}{Remote -- AnyCity, Anystate, Anycountry}":
                    "{International Research and Software Development Corporation}"
                    "{Greater Los Angeles Metropolitan Area, California, United States}",
            },
            "long-child-heading": {
                "{Backend Developer Intern}{Jan 2021 -- Aug 2021}":
                    "{Software Engineering Intern, Developer Experience and Platform Infrastructure}"
                    "{January 2021 -- August 2021}",
            },
        }
        for case, replacements in cases.items():
            with self.subTest(case=case):
                source = self.source
                for before, after in replacements.items():
                    self.assertIn(before, source)
                    source = source.replace(before, after)
                reader, log = self.compile_case(case, source)
                self.assert_clean_log(log)
                self.assertEqual(len(reader.pages), 1)
                text = compact(reader.pages[0].extract_text())
                for replacement in replacements.values():
                    for field in re.findall(r"\{([^{}]+)\}", replacement) or [replacement]:
                        self.assertIn(compact(field.replace("--", "–")), text)
                self.assertEqual(links(reader), set(re.findall(r"\\href\{([^}]+)\}", source)))

    def test_heading_and_item_font_sizes_do_not_leak(self):
        preamble = self.source.split(r"\begin{document}", 1)[0]
        body = r"""
\begin{document}
\begin{itemize}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\resumeSectionType{Languages}{:}{JavaScript, Python}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\resumeTrioHeading{Project}{Languages}{Source}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\resumeQuadHeading{Role}{Dates}{Company}{Location}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\resumeQuadHeadingChild{Intern}{Dates}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\resumeItem{A bullet point with enough words to exercise paragraph layout.}
\makeatletter\typeout{REVIEW-SIZE=\f@size}\makeatother
\end{itemize}
\end{document}
"""
        _, log = self.compile_case("macro-font-scope", preamble + body)
        self.assert_clean_log(log)
        sizes = re.findall(r"REVIEW-SIZE=([\d.]+)", log)
        self.assertEqual(len(sizes), 6)
        self.assertEqual(len(set(sizes)), 1, sizes)


if __name__ == "__main__":
    unittest.main()
