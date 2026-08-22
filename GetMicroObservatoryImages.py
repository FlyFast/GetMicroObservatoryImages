"""Download recent exoplanet FITS images from MicroObservatory."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


IMAGE_DIRECTORY_URL = (
	"https://waps.cfa.harvard.edu/microobservatory/"
	"MOImageDirectory/ImageDirectory.php?SortBy=Date&SortPos=DESC&"
	"SearchFor=ExoPlanets&Type=Object&SortRange=30"
)
USER_AGENT = "GetMicroObservatoryImages/1.0"
FITS_SUFFIXES = (".fits", ".fit", ".fits.gz", ".fit.gz")
METADATA_FILENAME = "metadata.json"
LOGGER = logging.getLogger(__name__)


class ImageTableParser(HTMLParser):
	"""Collect image rows and their metadata from the directory table."""

	def __init__(self) -> None:
		super().__init__()
		self.in_data_body = False
		self.in_row = False
		self.in_cell = False
		self.cell_text: list[str] = []
		self.cell_hrefs: list[str] = []
		self.row_cells: list[tuple[str, list[str]]] = []
		self.rows: list[dict[str, str]] = []

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		attributes = dict(attrs)
		if tag == "tbody" and attributes.get("id") == "data_view_body":
			self.in_data_body = True
		elif self.in_data_body and tag == "tr":
			self.in_row = True
			self.row_cells = []
		elif self.in_row and tag == "td":
			self.in_cell = True
			self.cell_text = []
			self.cell_hrefs = []
		elif self.in_cell and tag == "a":
			href = attributes.get("href")
			if href:
				self.cell_hrefs.append(href)

	def handle_data(self, data: str) -> None:
		if self.in_cell:
			self.cell_text.append(data.strip())

	def handle_endtag(self, tag: str) -> None:
		if self.in_cell and tag == "td":
			text = " ".join(part for part in self.cell_text if part)
			self.row_cells.append((text, self.cell_hrefs))
			self.in_cell = False
		elif self.in_data_body and tag == "tr":
			if self.row_cells:
				self._add_row()
			self.in_row = False
		elif tag == "tbody" and self.in_data_body:
			self.in_data_body = False

	def _add_row(self) -> None:
		cells = self.row_cells
		if len(cells) < 14:
			return
		fits_url = next(
			(
				href
				for _, hrefs in cells
				for href in hrefs
				if urlparse(href).path.lower().endswith(FITS_SUFFIXES)
			),
			None,
		)
		if not fits_url:
			return

		self.rows.append(
			{
				"Image Filename": cells[0][0],
				"Date & Time (UT)": cells[1][0],
				"Open JS9/4L": cells[2][1][0] if cells[2][1] else "",
				"FITS Image": fits_url,
				"Field of View": cells[4][0],
				"Exposure Time (sec)": cells[5][0],
				"Filter": cells[6][0],
				"Object": cells[7][0],
				"Telescope": cells[8][0],
				"Site": cells[9][0],
				"User": cells[10][0],
				"Size (KB)": cells[11][0],
				"Weather": cells[-1][0],
			}
		)


def fetch_directory(url: str = IMAGE_DIRECTORY_URL) -> str:
	"""Return the directory page as text."""
	request = Request(url, headers={"User-Agent": USER_AGENT})
	with urlopen(request, timeout=30) as response:
		return response.read().decode(response.headers.get_content_charset() or "utf-8")


def find_image_metadata(page: str, base_url: str = IMAGE_DIRECTORY_URL) -> list[dict[str, str]]:
	"""Extract unique image metadata in the page's displayed order."""
	parser = ImageTableParser()
	parser.feed(page)
	seen: set[str] = set()
	metadata = []
	for row in parser.rows:
		row["FITS Image"] = urljoin(base_url, row["FITS Image"])
		if row["FITS Image"] not in seen:
			metadata.append(row)
			seen.add(row["FITS Image"])
	return metadata


def timestamped_path(path: Path, run_timestamp: str) -> Path:
	"""Add a run timestamp before a file's extension."""
	return path.with_name(f"{path.stem}_{run_timestamp}{path.suffix}")


def write_metadata(
	metadata: list[dict[str, str]], output_dir: Path, filename: str
) -> None:
	"""Write metadata for every image listed on the webpage."""
	output_dir.mkdir(parents=True, exist_ok=True)
	with (output_dir / filename).open("w", encoding="utf-8") as metadata_file:
		json.dump(metadata, metadata_file, indent=2)
		metadata_file.write("\n")


def download_images(metadata: list[dict[str, str]], output_dir: Path) -> tuple[int, int, int]:
	"""Download URLs into output_dir, returning (downloaded, skipped, errors)."""
	output_dir.mkdir(parents=True, exist_ok=True)
	downloaded = 0
	skipped = 0
	errors = 0

	for image in metadata:
		is_dark = (
			image["Filter"].strip().lower() == "opaque"
			and image["Object"].strip().lower() == "calibration"
		)
		image_url = image["FITS Image"]
		filename = Path(urlparse(image_url).path).name
		if not filename:
			LOGGER.warning("Skipping FITS URL with no filename: %s", image_url)
			continue
		destination_dir = output_dir / "Darks" if is_dark else output_dir
		destination_dir.mkdir(parents=True, exist_ok=True)
		destination = destination_dir / filename
		if destination.exists():
			print(f"Skipping {filename} (already downloaded)")
			LOGGER.info("Skipped FITS file (already downloaded): %s", destination)
			skipped += 1
			continue

		try:
			request = Request(image_url, headers={"User-Agent": USER_AGENT})
			with urlopen(request, timeout=60) as response, destination.open("wb") as image:
				while chunk := response.read(1024 * 1024):
					image.write(chunk)
		except Exception:
			LOGGER.exception("Error downloading FITS file %s from %s", filename, image_url)
			print(f"Error downloading {filename}; see the logfile for details")
			errors += 1
			continue

		print(f"Downloaded {filename}")
		LOGGER.info("Downloaded FITS file: %s", destination)
		downloaded += 1

	return downloaded, skipped, errors


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"-o",
		"--output-dir",
		type=Path,
		default=Path("images"),
		help="directory in which to save FITS files (default: images)",
	)
	parser.add_argument(
		"--log-file",
		type=Path,
		default=Path("GetMicroObservatoryImages.log"),
		help="logfile path (default: GetMicroObservatoryImages.log)",
	)
	args = parser.parse_args()
	run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
	log_file = timestamped_path(args.log_file, run_timestamp)
	metadata_file = timestamped_path(Path(METADATA_FILENAME), run_timestamp)

	log_file.parent.mkdir(parents=True, exist_ok=True)
	logging.basicConfig(
		filename=log_file,
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(message)s",
		force=True,
	)
	LOGGER.info("Program run started")

	try:
		metadata = find_image_metadata(fetch_directory())
		write_metadata(metadata, args.output_dir, metadata_file.name)
		downloaded, skipped, errors = download_images(metadata, args.output_dir)
	except Exception:
		LOGGER.exception("Program run failed")
		print("Program failed; see the logfile for details")
		return 1

	LOGGER.info(
		"Program run finished: found=%d downloaded=%d skipped=%d errors=%d",
		len(metadata),
		downloaded,
		skipped,
		errors,
	)
	print(
		f"Found {len(metadata)} FITS files: {downloaded} downloaded, "
		f"{skipped} skipped, {errors} errors"
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
