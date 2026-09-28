# Local User Access Listing Extractor

This application reads PDF user listings and creates
`output/User_Access_Listing.xlsx`. It first uses a fast local embedded-text parser.
Pages without a usable text layer fall back to a locally installed Ollama vision
model. Each detected location receives its own worksheet. Processing is sequential
and fully local.

## Requirements

- Windows, macOS, or Linux with Python 3.10 or newer
- Ollama running locally
- A vision-capable Ollama model already installed (the app never downloads one)

## Setup

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate` instead.

Copy `.env.example` to `.env` and set `OLLAMA_MODEL` to the exact model name
reported by:

```powershell
ollama list
```

The default is `qwen2.5vl:7b`, but the application does not assume it is installed.
Before the first image-only page uses the vision fallback, it checks both the
Ollama server and configured model. To confirm Ollama is running locally,
`ollama list` should complete successfully; the default service address is
`http://localhost:11434`.

## Run

1. Put one or more PDF files in `input/`.
2. Activate the virtual environment.
3. Run:

```powershell
python main.py
```

The result appears at `output/User_Access_Listing.xlsx`.

Text-layer PDFs are parsed directly without Ollama. Image-only pages are rendered
at high resolution, mildly enhanced, sent only to the local Ollama instance,
validated, and deleted before the next page is processed. A
`Review Required` value of `YES` marks low-confidence, incomplete, unresolved, or
inherited-location records. Generic failures are recorded in a `PROCESSING ISSUES`
sheet without extracted user content.

## Configuration

Settings in `.env` include:

- `OLLAMA_MODEL`: installed vision-capable model name
- `OLLAMA_HOST`: local Ollama URL
- `PDF_RENDER_SCALE`: PDF render scale (default `4.0`)
- `OLLAMA_TIMEOUT`: request timeout in seconds
- `OLLAMA_NUM_CTX`: model context window (default `8192` for high-resolution pages)
- `MAX_EXTRACTION_RETRIES`: retries after the first attempt
- `REVIEW_CONFIDENCE_THRESHOLD`: default `0.80`
- `IMAGE_CONTRAST` and `IMAGE_SHARPNESS`: mild preprocessing factors

## Privacy

No cloud or web service is used. PDFs, page images, model requests, and Excel files
remain on the machine. The program does not print extracted usernames, emails, or
rows, and generated page images are removed even when page extraction fails.
`input/`, `output/`, `temp/`, PDFs, workbooks, and `.env` are excluded from Git.
