# Documents

Upload your customer's procedures, escalation matrices, runbooks and playbooks. Mentis reads them, indexes them and finds the passages that answer analysts' questions.

## Upload

Open **Documents** and drop files on the dashed area, or select **Upload documents**. You can upload several files at once.

Accepted: **PDF, DOCX, PPTX, XLSX**, up to 50 MB each.

Refused, with the reason shown:

- macro-enabled files (.docm, .xlsm, .pptm) and old formats (.doc, .xls, .ppt): save them in the modern format first
- password-protected or encrypted Office files

A PDF that only restricts printing or copying is accepted and read normally. A PDF that needs a password to open is stored but ends as **Failed** ("The file is password-protected"): remove the password and upload it again.
- files whose content does not match the extension

## Versions

Uploading a file with the **same name** as an existing document adds a new version. Only one version is **in use** at a time; older ones stay available.

| State | Meaning |
| --- | --- |
| Queued / Processing | Mentis is reading and indexing the file |
| Active | The version answers use |
| Waiting approval | Read, waiting for you to approve it |
| Archived | An older version, not in use |
| Rejected | You rejected it in the preview |
| Failed | Could not be read or indexed; the error is shown. Use **Retry** after fixing the cause |

A failed or rejected version never replaces the one in use. Uploading a file identical to the active version is refused.

If the worker stops in the middle of a document (restart, crash, timeout), the version becomes **Failed** with "Processing was interrupted" within about half an hour: use **Retry**. A version left **Queued** because its job was lost is queued again automatically.

Open **Versions** on a row to see them all. From there you can preview, download the original, **Make active** an older version, approve or reject.

## Preview: check what Mentis read

Select the eye icon or **Preview**. Each page (PDF), section (Word, split at top-level headings), slide (PowerPoint) or sheet (Excel) is shown with:

- **Original**: the page image for PDFs; for the other formats, a link to the original file
- **What Mentis read**: the extracted text, with headings and tables
- **Badges**: Native text or **OCR** with its confidence, tables found, and warnings

Pages with a warning icon need a look:

- **Low OCR confidence**: a poor scan; the text may contain errors
- **No text**: nothing could be read (blank page or unreadable image)
- **Merged cells** (Excel): check that values landed in the right columns
- **Truncated**: only the first part was read (very large sheets or documents)

Text inside images in slides (screenshots, diagrams) is read with OCR and shown as "Text in image".

## Test a question

At the top of the preview, type a question an analyst would ask (for example "who is the on-call contact for high severity?") and select **Find passages**. Mentis shows the passages of **this version** it would use, with the page and how well they match. Select the page button to jump to it.

- Use it before approving a new version, to check that the important answers are found.
- If nothing relevant comes back, the text may be poorly read (check the warnings) or the answer is not in the document.
- It works on pending versions too; analysts only ever get answers from the version in use.

## Approval before publishing

If **Approve new document versions before publishing** is on in **Settings**, new versions wait in **Waiting approval**. Open the preview and choose **Approve and publish** or **Reject**.

## Rename and delete

- Pencil icon: rename. Later uploads with the new name become new versions of it.
- Trash icon: deletes the document with all its versions and stored files. Answers stop using it.

> Tip: prefer native PDFs and Office files over scans. Scans are read with OCR and can contain errors; check them in the preview.
