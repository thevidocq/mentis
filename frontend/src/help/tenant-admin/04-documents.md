# Documents

Upload your customer's procedures, escalation matrices, runbooks and playbooks. Mentis reads them, indexes them and finds the passages that answer analysts' questions.

## The page

**Documents** works like a document manager:

- **On the left, the list.** Search by name, and filter **All**, **In use** or **To review**. Documents that need you (**Failed**, **To approve**, **Processing**) are grouped at the top under *Needs attention*; then *In use*, then *Not in use*.
- **On the right, the Overview** when you open the page (or select **Overview** at the top of the list): documents in use, pages read (and how many with OCR), passages searchable, questions asked in chats on this customer in the last 30 days and how many found nothing; what needs attention, with a direct **Retry** or **Review**; content in use by file type, last indexed, oldest in use, pages to check; recent uploads and approvals. Select any line to open that document.
- **On the right, the selected document**, once you select one. Its name and state, the actions, and four tabs: **Preview**, **Text read**, **Versions**, **Test a question**. A column with the details and the latest versions is on the right on wide screens.

On a phone the list fills the screen; tap a document to open it, **‹** to go back.

## Upload

Select **Upload** above the list, or drop files on the list. You can upload several files at once; a single new document opens when it is uploaded.

Accepted: **PDF, DOCX, PPTX, XLSX, Markdown (.md, .markdown), JSON, CSV, TSV, YAML (.yaml, .yml) and pictures (PNG, .jpg, .jpeg)**, up to 50 MB each. Empty files are refused.

- **Markdown** (exports of wikis such as Confluence, Notion, GitHub): one section per top-level heading; must be UTF-8 text.
- **JSON**: a file downloaded from Mentis as JSON (Documents → download → JSON) is read back with its own pages, so documentation moves between customers or installations as it was. Any other JSON (contact lists, escalation matrices exported from a tool) becomes readable text: one section per top-level key or per item, lists of records as tables. It must be valid UTF-8 JSON.
- **CSV / TSV** (contact lists, escalation matrices, shifts exported from Excel or a tool): read as one table, like an Excel sheet. Comma, semicolon, pipe and tab separators are recognised; a file without a consistent separator is read as one column of lines. Save as **CSV UTF-8**; up to 5,000 rows and 500 columns are read. In TSV, quotes are plain text.
- **YAML** (`.yaml`, `.yml`: Sigma rules, SOAR playbooks, configurations): one section per YAML document (separated by `---`), named after its `title`, `name` or `id`; the text is kept exactly as written, so analysts can ask what a rule detects. Comments are kept with the document they precede. Must be valid UTF-8 YAML, at most 200,000 values.
- **Pictures** (PNG, JPEG: screenshots of a matrix, photos of a procedure, diagrams with text): read with OCR like a scanned page, with the confidence score; the picture is shown in the preview. At most 50 million pixels (e.g. 7000 × 7000). Check the **Text read** tab: OCR can misread small or blurred text. A picture with no readable text (a photo, a diagram without labels) ends as **Failed**: Mentis answers from text only.

Refused, with the reason shown:

- macro-enabled files (.docm, .xlsm, .pptm) and old formats (.doc, .xls, .ppt): save them in the modern format first
- password-protected or encrypted Office files
- files whose content does not match the extension

A PDF that only restricts printing or copying is accepted and read normally. A PDF that needs a password to open is stored but ends as **Failed** ("The file is password-protected"): remove the password and upload it again.

## Actions

At the top of the document:

- **Approve vN** / **Reject**: when the latest version waits for approval.
- **Retry vN**: when the latest version failed (fix the cause first, e.g. the embedding service).
- **New version**: upload a file as the next version of **this** document, whatever its file name (same file type).
- Download icon: a menu with the formats of the version on screen: **Original** (the file as uploaded), **Markdown** (the text Mentis read, page by page, with a header: customer, version, file, date, SHA-256) and **JSON** (the same text plus the passages as indexed, with page and section: to import the documentation into another system). Markdown and JSON are available once the version has been read.
- **⋯**: **Rename**, **Versions and restore**, **Delete document**.

## Download all

**All** (download icon) at the top of the list downloads a ZIP with every document **in use** of the customer, in the format you pick: originals, Markdown or JSON. A `manifest.json` in the ZIP lists the files, their versions and how many documents were left out (waiting for approval, not read yet, or failed). Each ZIP is limited to 300 MB of content in every format (set by the administrator), and one ZIP is prepared at a time: if another one is being prepared, try again in a minute. Every download is in the audit log.

## Versions

Uploading a file with the **same name** as an existing document (or with **New version**) adds a new version. Only one version is **in use** at a time; older ones stay available.

| State | Meaning |
| --- | --- |
| Queued / Processing | Mentis is reading and indexing the file |
| Active | The version answers use |
| Waiting approval | Read, waiting for you to approve it |
| Archived | An older version, not in use |
| Rejected | You rejected it |
| Failed | Could not be read or indexed; the error is shown. Use **Retry** after fixing the cause |

A failed or rejected version never replaces the one in use. Uploading a file identical to the active version is refused.

If the worker stops in the middle of a document (restart, crash, timeout), the version becomes **Failed** with "Processing was interrupted" within about half an hour: use **Retry**. A version left **Queued** because its job was lost is queued again automatically.

The **Versions** tab lists them all: **View** one in the preview, download it, **Make active** an older one, approve, reject or retry.

## Preview and Text read: check what Mentis read

**Preview** shows each page as in the original (PDF) or the picture itself (PNG, JPEG); for the other formats, which have no page image, it shows the text read. **Text read** always shows the extracted text, with headings and tables, and how it was read: native text or **OCR** with its confidence, and the tables found. Move between pages, sections (Word and Markdown at top-level headings, JSON per key or item, YAML per document), slides, sheets or tables (CSV) with **‹ ›**.

Warnings next to the page number need a look:

- **Low OCR confidence**: a poor scan; the text may contain errors
- **No text**: nothing could be read (blank page or unreadable image)
- **Merged cells** (Excel): check that values landed in the right columns
- **Truncated**: only the first part was read (very large sheets or documents)

Text inside images in slides (screenshots, diagrams) is read with OCR and shown as "Text in image".

## Test a question

In **Test a question**, type a question an analyst would ask (for example "who is the on-call contact for high severity?") and select **Find passages**. Mentis shows the passages of the version on screen it would use, with the page and how well they match. Select the page button to open it in the preview.

- Use it before approving a new version, to check that the important answers are found.
- If nothing relevant comes back, the text may be poorly read (check the warnings) or the answer is not in the document.
- It works on pending versions too; analysts only ever get answers from the version in use.

## Approval before publishing

If **Approve new document versions before publishing** is on in **Settings**, new versions wait in **Waiting approval** and the document shows under *Needs attention*. Check it in **Preview** and **Test a question**, then choose **Approve** or **Reject** at the top.

## Rename and delete

From **⋯**:

- **Rename**: later uploads with the new name become new versions of it.
- **Delete document**: deletes the document with all its versions and stored files. Answers stop using it.

> Tip: prefer native PDFs and Office files over scans. Scans are read with OCR and can contain errors; check them in Text read.
