# GetMicroObservatoryImages
Download the lastest exoplanet FITS imagery from the Micro Observatory.

This code has been deprecated.
Not recommended for use on the current Micro Observatory site.

This program was developed with Copilot AI.

## Usage

Run the downloader from this directory:

```text
python3 GetMicroObservatoryImages.py
```

Files are saved in `images/` by default. Use `--output-dir` to choose another
directory. Existing files are skipped, so the command can be run repeatedly.
Each run is recorded in a new timestamped logfile based on
`GetMicroObservatoryImages.log`; use `--log-file` to choose another filename
base. Download failures include their error traceback.
Metadata for every FITS file listed by the webpage is written to
 a new timestamped `images/metadata_*.json` file. All FITS files are downloaded
 regardless of their Weather value.
Files whose Filter is `Opaque` and Object is `Calibration` are saved in
`images/Darks/` regardless of their Weather value.
