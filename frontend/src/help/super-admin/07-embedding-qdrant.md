# Embedding and Qdrant

Mentis turns every chunk of text into a vector with an **embedding model**, and stores the vectors in **Qdrant**, one collection per customer. Questions are matched against these vectors to find the right passages.

## Embedding service

By default the local `embeddings` container runs **BAAI/bge-m3** (multilingual, good for Italian and English) with Hugging Face Text Embeddings Inference. Nothing leaves your server.

Any OpenAI-compatible endpoint works instead:

| Service | Endpoint URL example |
| --- | --- |
| Local TEI (default) | http://embeddings/v1 |
| Ollama | http://ollama:11434/v1 |
| vLLM | http://vllm:8000/v1 |
| Cloud provider | its /v1 URL, with an API key |

> Using a cloud embedding service sends the text of every document to that provider, even if the chat uses a local LLM.

Select **Test connection** after saving: it reports the model and the vector size.

A saved API key is only sent to the address it was saved for: when you change the address, enter the key again (leave it empty for a service without one). The same applies to a configuration import that changes the address: the key is dropped. If the server's `.env` sets `MENTIS_EMBEDDING_ALLOWED_URLS`, only those addresses are accepted. A change of address is recorded in **Logs** as a warning, since every document and question goes to the embedding service.

## Changing model: reindex

Vectors from different models cannot be mixed. After changing the model, the page shows **Reindex needed** and new uploads fail until you select **Reindex everything**. Reindexing rebuilds every customer's collection from the text already extracted (documents are not read again) and shows its progress. While it runs, chat answers pause with a message saying so: an answer never comes from a half-built index. A document that cannot be indexed is tried once more; if any still fail, the reindex shows **failed** with their names and answers stay paused until a new **Reindex everything** succeeds (also when the reindex failed while clearing the old index). The same happens if the worker stops in the middle of a reindex (a restart): after the job's time limit the page lets you start it again.

## Reprocess all documents

After an upgrade that improves how documents are read (the release note says so), select **Reprocess all documents**: every document in use or waiting is read again from its original file, and its pages, sections and vectors are replaced in place. Documents stay in answers meanwhile, and approvals and versions do not change. A document whose file can no longer be read keeps its previous reading and is listed under the progress. If Qdrant fails just after a document was read again, its old index entries may remain: the page says so, and **Reindex everything** (or the daily cleanup) removes them. It is not offered while a reindex is needed or running.

## Index status

The page shows the model the index was built with, the number of collections and of vectors. Deleting a document or a customer removes its vectors.
