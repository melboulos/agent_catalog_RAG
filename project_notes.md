# Agent Catalog RAG — Project Notes

These notes describe the design, implementation, and key details of the **Agent Catalog RAG system.

---

## 1. Overview

**Agent Catalog Q&A** is a production-ready question-answering pipeline that integrates:

- **Couchbase**: Cache & vector store
- **FTS (Full Text Search)**: Fast vector candidate retrieval
- **AWS Bedrock**:
  - **Titan embeddings** for vector search
  - **LLaMA3 LLM** for answer generation and semantic reranking
- **Streamlit**: Interactive front-end for Q&A and audit visualization

The system prioritizes **speed and relevance**:

1. **Cache** → return cached answer if available.
2. **Vector Search** → retrieve vector candidates from Couchbase FTS.
3. **Semantic Reranking** → rerank vector hits using LLM.
4. **Threshold Evaluation** → display vector answers above threshold; below threshold answers are highlighted in red.
5. **LLM Fallback** → generate answer only if vector fails threshold or cache is missing.
6. **Audit Logging** → store all results, scores, and latency.

---

## 2. Data Flow

```text
User Question
       ↓
   Pipeline
       ├─ Cache lookup in Couchbase QA collection
       │      └─ Return if found
       ├─ Vector Search using Titan embeddings
       │      ├─ Retrieve top-k hits via FTS
       │      └─ Normalize scores to 0–100
       ├─ Semantic Rerank via LLM
       │      └─ Adds semantic_score for each vector hit
       ├─ Threshold Evaluation
       │      └─ Below-threshold vectors trigger LLM fallback
       └─ LLM Fallback via Bedrock
              └─ Answer generated & stored in QA collection
       ↓
     Audit logging
       ↓
   Streamlit UI display

---

**3. Couchbase Configuration**

**Bucket / Collections**:

- **Bucket**: `agent_catalog`
- **Scope**: `agent_scope`
- **QA Collection**: `qa`
- **Audit Logs Collection**: `audit_logs`

**FTS Vector Index**:

- Name: `agent_vector_idx`
- Fields indexed: `embedding_vector`, `answer`
- Used for **semantic search** via REST API

**Connection Settings**:

```text
Connection string: couchbases://<cluster-address>
Username: cbimport
Password: <password>
CA Bundle: <path-to-root-certificate>

---

## **4. AWS Bedrock Integration**

This project uses **AWS Bedrock** for both embedding generation and LLM-powered answer generation.

### Embedding Model
- **Model**: `amazon.titan-embed-text-v1`
- **Purpose**: Generates vector embeddings for the user query to enable semantic search in Couchbase.

### LLM Model
- **Model**: `meta.llama3-70b-instruct-v1:0`
- **Purpose**:
  - Semantic reranking of vector hits
  - Generating answers when both cache and vector results are missing or below the threshold

### Boto3 Client Initialization

```python
import boto3

bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

**Embedding Generation**
def get_embedding(text: str):
    response = bedrock_runtime.invoke_model(
        modelId="amazon.titan-embed-text-v1",
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]

**LLM Answer Generation**
def generate_answer(question: str):
    response = bedrock_runtime.invoke_model(
        modelId="meta.llama3-70b-instruct-v1:0",
        body=json.dumps({"prompt": f"Answer concisely:\n\n{question}\n\nAnswer:"}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload.get("generation") or payload.get("generations", [{}])[0].get("text", "")

---

## **5. Vector Search and Semantic Reranking**

The project uses **Couchbase Full-Text Search (FTS) with vectors** to retrieve semantically relevant answers before falling back to the LLM.

### Vector Search via REST

```python
import requests
from requests.auth import HTTPBasicAuth

def vector_search_rest(embedding):
    query = {
        "fields": ["answer"],
        "knn": [{
            "field": "embedding_vector",
            "vector": embedding,
            "k": 10,  # TOP_K
            "num_candidates": 10
        }]
    }

    r = requests.post(
        CB_FTS_URL,
        headers={"Content-Type": "application/json"},
        auth=HTTPBasicAuth(CB_USERNAME, CB_PASSWORD),
        data=json.dumps(query),
        verify=CB_CA_BUNDLE
    )

    if r.status_code != 200:
        logging.error(f"FTS error {r.status_code}: {r.text}")
        return []

    hits = r.json().get("hits", [])
    logging.info(f"🔍 Raw FTS hits count: {len(hits)}")
    return hits
- Purpose: Retrieve the top K candidate answers based on embedding similarity.
- Normalization: Scores are normalized relative to the highest hit to give Vector Score out of 100.

**Semantic Reranking**
- To improve accuracy, vector hits are reranked semantically using the LLM.

def rerank_vector_hits(question: str, vector_rows: list):
    if not vector_rows:
        return vector_rows

    prompt_text = (
        "You are a semantic reranker.\n"
        "Rank the answers by relevance to the question.\n"
        "Return strict JSON only in the format: "
        "[{\"id\":0, \"score\":95}, {\"id\":1, \"score\":85}, ...]\n"
        f"Question:\n{question}\n\n"
        "Answers:\n" +
        "\n".join(f"{i}. {r['Answer']}" for i, r in enumerate(vector_rows)) +
        "\n\nDo not include any text outside the JSON array."
    )

    response = bedrock_runtime.invoke_model(
        modelId=LLM_MODEL_ID,
        body=json.dumps({"prompt": prompt_text}),
        contentType="application/json",
        accept="application/json"
    )

    payload = json.loads(response["body"].read())
    generation = payload.get("generation") or payload.get("generations", [{}])[0].get("text", "")

    # Parse JSON ranks
    first_json_start = generation.find('[')
    first_json_end = generation.rfind(']') + 1
    cleaned = generation[first_json_start:first_json_end]

    try:
        ranks = json.loads(cleaned)
        for r in vector_rows:
            r['semantic_score'] = 0
        for rank in ranks:
            idx = rank['id']
            score = rank['score']
            if 0 <= idx < len(vector_rows):
                vector_rows[idx]['semantic_score'] = score
        vector_rows.sort(key=lambda x: x['semantic_score'], reverse=True)
    except Exception as e:
        logging.warning(f"⚠️ Reranker JSON parse failed: {e}. Using FTS order.")
        for r in vector_rows:
            r['semantic_score'] = r['Vector Score']

    return vector_rows[:3]
- Vector Score: Represents normalized similarity from Couchbase FTS.
- Semantic Score: Refined relevance score from LLM reranker.
- Top 3: Only the top 3 reranked answers are returned for display and audit.

---

## **6. Cache Handling and Deduplication**

To improve performance and avoid repeated LLM calls, the system uses **Couchbase as a cache**. Answers retrieved from the cache are deduplicated against vector search results.

### Cache Lookup

```python
import hashlib
from couchbase.exceptions import DocumentNotFoundException

doc_id = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()
cache_answer = None
try:
    doc = qa_col.get(doc_id)
    cache_answer = doc.content_as[dict]["answer"]
    logging.info(f"🟡 Cache hit | question='{question}'")
except DocumentNotFoundException:
    logging.info(f"🟡 Cache miss | question='{question}'")

- Cache Key: SHA-256 hash of the normalized question string.
- Behavior: If found, the cached answer is added to the results with a Vector Score and semantic_score of 100.

Deduplication of Answers:
all_rows = []
seen_answers = set()

# Include cache answer first
if cache_answer:
    seen_answers.add(cache_answer)
    all_rows.append({
        "Source": "Cache",
        "Threshold": SCORE_THRESHOLD,
        "Vector Score": 100,
        "semantic_score": 100,
        "Latency (ms)": int((time.time() - start) * 1000),
        "Answer": cache_answer,
        "Below Threshold": False
    })

# Add reranked vector hits without duplicates
for row in vector_rows:
    if row["Answer"] not in seen_answers:
        seen_answers.add(row["Answer"])
        all_rows.append(row)
- Purpose: Avoid showing duplicate answers from cache and vector search.
- Ordering: Cache answer appears first, followed by top reranked vector hits.
- Top 3: Only the top 3 answers are kept for display and audit.

---

## **7. LLM Fallback Logic**

When neither the cache nor the vector search provides answers **above the threshold**, the system falls back to the **LLM** (AWS Bedrock) to generate a new answer.

### Triggering LLM

```python
if not all_rows or all(r["Vector Score"] < SCORE_THRESHOLD for r in all_rows):
    logging.info("🟢 LLM fallback for missing or below threshold answers")
    answer = generate_answer(question)
Condition: LLM is only called if:
1. No answers were found in cache/vector, or
2. All vector answers are below the SCORE_THRESHOLD.

Storing LLM Answer
Once generated, the LLM answer is stored in Couchbase for future cache hits:
qa_col.upsert(doc_id, {
    "type": "agent_scope.qa",
    "question": question,
    "answer": answer,
    "embedding_vector": embedding,
    "ts": datetime.now(timezone.utc).isoformat()
})
- Cache Key: Same SHA-256 hash of the question.
- Embedding: Stored alongside the LLM answer to allow future vector searches.
- Timestamp: Stored in UTC for audit tracking.

LLM Row Formatting
- The generated answer is appended to the results as:
row = {
    "Source": "LLM",
    "Threshold": SCORE_THRESHOLD,
    "Vector Score": 0,
    "semantic_score": 0,
    "Latency (ms)": int((time.time() - start) * 1000),
    "Answer": answer,
    "Below Threshold": False
}
all_rows.append(row)
- Vector Score is 0 because this answer did not come from the vector search.
- semantic_score is 0 because reranking is not needed for LLM-generated answers.

---

## **8. Streamlit UI and Grid Display**

The Streamlit interface allows users to ask questions, view results, and inspect audit logs. It presents vector and LLM answers in a **grid with rich formatting**.
### Page Setup

```python
st.set_page_config(page_title="Agent Catalog", layout="wide")
st.title("Agent Catalog Q&A")

- Uses wide layout for better table visibility.
- Page title and header set for clarity.

Question Input:
question = st.text_input("Ask a question")
Users type a question here.

Input is sent to run_pipeline() for processing.

Displaying Results in a Table

Results include:
-Source (Cache, Vector, LLM)
-Threshold
-Vector Score
-semantic_score
-Latency (ms)
-Answer
-Below Threshold flag
-Only top 3 answers are displayed.
df = pd.DataFrame(results)
df = df[[
    "#", "Source", "Threshold", "Vector Score", "semantic_score",
    "Latency (ms)", "Answer", "Below Threshold"
]]

AG-Grid Setup
-Uses st_aggrid for rich table functionality.
-Columns can have conditional formatting:
cell_style_jscode = JsCode("""
function(params) {
    if (params.value < 85 && params.data.Source === 'Vector') {
        return {'color': 'red', 'fontWeight': 'bold'};
    }
    return {};
}
""")
gb.configure_column("Vector Score", cellStyle=cell_style_jscode)
gb.configure_column("semantic_score", cellStyle=cell_style_jscode)

-Highlights vector scores below threshold in red and bold.
-Semantic scores are displayed next to vector scores for clarity.

Display Counters
st.markdown(
    f"**Cache:** {counters['Cache']} &nbsp;&nbsp; "
    f"**Vector:** {counters['Vector']} &nbsp;&nbsp; "
    f"**LLM:** {counters['LLM']}"
)
-Shows how many answers came from each source.

Audit Logs
-Last 20 audit entries displayed with st.expander:
st.header("Audit Logs (last 20)")

for row in cluster.query(query):
    audit = row
    ts = audit.get("ts", "")
    header = f"{audit['source']} | latency={audit['latency']}ms | ts={ts[11:19]}"
    with st.expander(header):
        st.json(audit)
Each log shows:
-source
-latency
-timestamp
-Full JSON for top3 answers

---

## **9. Audit and Logging**

The project keeps detailed logs and audit trails for all questions processed, including cache hits, vector search results, semantic reranking, and LLM fallbacks.

### Logging Configuration

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
-INFO level used for general operations.
-Logs timestamp, log level, and message.
-All major steps—embedding generation, FTS hits, reranker responses, cache hits, LLM fallbacks—are logged.

Audit Saving Function
def save_audit(source, latency, vector_score, question, top3):
    audit_col.insert(
        str(time.time()),
        {
            "source": source,
            "latency": latency,
            "vector_score": vector_score,
            "question": question,
            "top3": top3[:3],
            "ts": datetime.now(timezone.utc).isoformat()
        }
    )
    logging.info(
        f"📝 Audit saved | source={source} | latency={latency} | vector_score={vector_score} | question='{question}'"
    )
-Stores audit documents in Couchbase audit_logs collection.
-Saves top 3 answers, source, latency, vector score, and UTC timestamp.
-Logs a confirmation for each audit saved.

What is Tracked:
-Source: Cache, Vector, or LLM.
-Latency: Time taken for the pipeline to process the question (ms).
-Vector Score: Maximum vector similarity score for the results.

Top 3 Answers: Answer text with metadata:
-Answer
-Vector Score
-semantic_score
-Threshold
-Below Threshold flag
-Timestamp: When the audit entry was created.

Streamlit Display of Audit Logs
-Last 20 audit entries shown in expandable panels:
st.header("Audit Logs (last 20)")

query = f"""
SELECT a.*
FROM `{CB_BUCKET}`.`{CB_SCOPE}`.`{CB_AUDIT_COLLECTION}` a
ORDER BY a.ts DESC
LIMIT 20
"""

for row in cluster.query(query):
    audit = row
    ts = audit.get("ts", "")
    header = f"{audit['source']} | latency={audit['latency']}ms | ts={ts[11:19]}"
    with st.expander(header):
        st.json(audit)


-Each expander contains the full JSON of the audit entry.
-Users can inspect vector scores, semantic scores, and below-threshold flags for transparency.

Benefits
-Ensures traceability of all responses.
-Helps debug pipeline issues or verify correctness.
-Supports monitoring of thresholds and LLM fallbacks in production.

---

## **10. Deployment and Production Notes**

This section covers considerations for running the Agent Catalog pipeline in production.

### System Requirements

- **Python 3.10+**
- **Streamlit** for UI
- **Couchbase Server 8.0+** with:
  - Bucket for QA (`agent_catalog`)
  - Scope (`agent_scope`)
  - Collections (`qa` and `audit_logs`)
  - FTS Index for vector search
- **AWS Bedrock** access for embeddings and LLM inference
- **TLS/CA bundle** for secure Couchbase connection
- **Network access** to Couchbase FTS API and Bedrock endpoints

### Configuration

- Update `hash_agentcatalog.py` with:
  - Couchbase connection string, username, password
  - Bucket, scope, collection names
  - FTS index URL
  - AWS Bedrock region and model IDs
  - TLS/CA bundle path
- Set `SCORE_THRESHOLD` for vector acceptance (default `85`)
- Set `TOP_K` to control number of vector hits returned (default `10`)

### Running the App

```bash
streamlit run hash_agentcatalog.py

-Open the browser to interact with Agent Catalog Q&A

-Ask questions to see results from:
1. Cache (QA collection)
2. Vector search (FTS + embedding similarity)
3. LLM fallback (Bedrock) if missing or below threshold

Deployment Considerations:

Security
-Use secure credentials management for Couchbase and AWS keys.
-TLS/CA bundle ensures encrypted connections to Couchbase.

Scalability
-Vector FTS queries may take longer with large datasets; consider batch processing or caching.
-LLM fallbacks are slower; cache all answers to reduce repeat calls.

Monitoring
-Audit logs track latency, source, vector scores, and thresholds.
-Streamlit UI shows last 20 audit logs for visibility.
-Logging is at INFO level; adjust if verbose output is needed.

Maintenance
-Periodically update embeddings for new QA entries.
-Maintain FTS index and Couchbase collections for performance.
-Monitor AWS Bedrock model updates and adjust model IDs if necessary.
-End-to-End Workflow
-Question → check Cache → Vector search → Semantic rerank → Threshold check → LLM fallback → Store in QA → Audit → Display in UI
Ensures fast responses, traceability, and fallback reliability.

**Summary**
This setup provides end-to-end QA pipeline that integrates:
-Couchbase cache and vector search
-Semantic reranking using LLM
-AWS Bedrock embeddings and LLM
-Audit logging for monitoring
-Streamlit UI for interaction
