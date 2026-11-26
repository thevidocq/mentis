# Documents

Upload your customer's procedures, escalation matrices, runbooks and playbooks. Mentis reads them, indexes them and finds the passages that answer analysts' questions.

## The page

**Documents** works like a document manager:

- **On the left, the list.** Search by name, and filter **All**, **In use** or **To review**. Documents that need you (**Failed**, **To approve**, **Processing**) are grouped at the top under *Needs attention*; then *In use*, then *Not in use*.
- **On the right, the selected document.** Its name and state, the actions, and four tabs: **Preview**, **Text read**, **Versions**, **Test a question**. A column with the details and the latest versions is on the right on wide screens.

On a phone the list fills the screen; tap a document to open it, **‹** to go back.

## Upload

Select **Upload** above the list, or drop files on the list. You can upload several files at once; a single new document opens when it is uploaded.

Accepted: **PDF, DOCX, PPTX, XLSX**, up to 50 MB each.

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
- Download icon: the original file of the version on screen.
- **⋯**: **Rename**, **Versions and restore**, **Delete document**.

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

**Preview** shows each page as in the original (PDF); for Word, PowerPoint and Excel, which have no page image, it shows the text read. **Text read** always shows the extracted text, with headings and tables, and how it was read: native text or **OCR** with its confidence, and the tables found. Move between pages, sections (Word, split at top-level headings), slides or sheets with **‹ ›**.

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
