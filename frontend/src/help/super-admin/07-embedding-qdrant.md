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

## Changing model: reindex

Vectors from different models cannot be mixed. After changing the model, the page shows **Reindex needed** and new uploads fail until you select **Reindex everything**. Reindexing rebuilds every customer's collection from the text already extracted (documents are not read again) and shows its progress. Answers may miss documents until it finishes.

## Index status

The page shows the model the index was built with, the number of collections and of vectors. Deleting a document or a customer removes its vectors.
