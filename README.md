# Agent Catalog RAG

## Overview

**Agent Catalog Q&A** 
- **Cache → Vector → LLM** search flow
- **Couchbase** as vector and audit store
- **AWS Bedrock** for embeddings and LLM generation
- Streamlit UI for interactive question answering

It is designed to:
- Serve answers from cache if available
- Perform **vector search** over Couchbase FTS + vector index
- Rerank vector results using **semantic similarity** via LLM
- Fallback to **LLM generation** if no vector or cache hits meet threshold
- Maintain audit logs for all queries
---

## Features
- **Cache-first** approach to minimize LLM calls
- **Vector search** using Couchbase Full Text Search (FTS) with embeddings
- **Semantic reranking** for better relevance
- **Thresholding** for vector scores
- **Audit logging** of top answers, latency, and scores
- **Streamlit UI** with interactive table
- **End-to-end production ready** with no config or code loss
---

## Architecture
```text
User Question
     │
     ▼
  Cache Check ──► Hit: return
     │
     ▼
 Vector Search (FTS + embedding)
     │
     ▼
 Semantic Rerank (LLM)
     │
     ▼
Threshold Check
 ┌───────────────┐
 │  Above        │─► Return vector results
 │  Below        │─► Call LLM → Return LLM + vector
 └───────────────┘
     │
     ▼
 Store in Cache / Audit
######################

Installation
# Clone repository
git clone https://github.com/yourusername/agent-catalog.git
cd agent-catalog

# Install dependencies
pip install -r requirements.txt


Required:
Python 3.11+
Couchbase cluster with FTS + vector index
AWS account with Bedrock access
Streamlit for UI

**Configuration**
**Edit the following in hash_agentcatalog.py:**

CB_CONN_STR = "couchbases://<cluster>.cloud.couchbase.com"
CB_USERNAME = "<username>"
CB_PASSWORD = "<password>"
CB_BUCKET = "agent_catalog"
CB_SCOPE = "agent_scope"
CB_QA_COLLECTION = "qa"
CB_AUDIT_COLLECTION = "audit_logs"
CB_FTS_URL = "https://<cluster>.cloud.couchbase.com:18094/api/index/<bucket>.<scope>.<vector_index>/query"
CB_CA_BUNDLE = "<path-to-root-certificate>"
BEDROCK_REGION = "us-east-1"
EMBED_MODEL_ID = "amazon.titan-embed-text-v1"
LLM_MODEL_ID = "meta.llama3-70b-instruct-v1:0"
SCORE_THRESHOLD = 85
TOP_K = 10
Usage
--> streamlit run hash_agentcatalog.py
Type a question in the input box
Top 3 answers are displayed with:
-Source (Cache, Vector, LLM)
-Threshold
-Vector Score
-Semantic Score
-Latency
-Below Threshold flag
