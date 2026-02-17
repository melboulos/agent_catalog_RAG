<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Agent Catalog (RAG) — Cache → Vector → LLM</title>
</head>

<body>

<h1>🧠 Agent Catalog</h1>

<p>
<strong>Agent Catalog</strong> is a production-grade AI retrieval system that enforces
<strong>deterministic decision-making</strong> across
<strong>Cache → Vector Search → LLM fallback</strong>.
</p>

<p>
It integrates <strong>Couchbase Vector Search</strong>, <strong>AWS Bedrock</strong>,
and <strong>Streamlit</strong> to build explainable, auditable, and agent-ready AI pipelines.
</p>

<hr/>

<h2>✨ Key Features</h2>

<ul>
  <li>🔁 Deterministic routing: Cache → Vector → LLM</li>
  <li>🧠 Semantic reranking using LLMs (controlled & bounded)</li>
  <li>📊 Side-by-side scoring (Vector + Semantic)</li>
  <li>🧾 Full audit logging for observability</li>
  <li>🚦 Threshold-based LLM invocation</li>
  <li>🧩 Agent-ready architecture</li>
</ul>

<hr/>

<h2>🏗️ Architecture Overview</h2>

<pre>
User Question
     |
     v
[ Cache Lookup ]
     |
     |-- HIT → Return Cached Answer
     |
     v
[ Vector Search (Couchbase FTS) ]
     |
     v
[ Semantic Reranker (LLM) ]
     |
     |-- Above Threshold → Return Vector Result
     |
     v
[ LLM Fallback ]
     |
     v
Store + Return Answer
</pre>

<hr/>

<h2>⚙️ Configuration</h2>

<p>
All runtime configuration lives at the <strong>top of the script</strong>:
</p>

<ul>
  <li><strong>Couchbase cluster & collections</strong></li>
  <li><strong>FTS vector index endpoint</strong></li>
  <li><strong>AWS Bedrock embedding + LLM models</strong></li>
  <li><strong>Score thresholds</strong></li>
  <li><strong>Retrieval depth (TOP_K)</strong></li>
</ul>

<blockquote>
  ⚠️ <strong>Security note:</strong> Secrets should be moved to environment variables in production.
</blockquote>

<hr/>

<h2>🚀 Running Locally</h2>

<pre><code>pip install -r requirements.txt
streamlit run hash_agentcatalog.py</code></pre>

<p>
The UI will launch with:
</p>

<ul>
  <li>Top results table (Cache / Vector / LLM)</li>
  <li>Color-coded threshold violations</li>
  <li>Semantic score visualization</li>
  <li>Audit log explorer</li>
</ul>

<hr/>

<h2>📊 Scoring Model</h2>

<table border="1" cellpadding="6" cellspacing="0">
  <tr>
    <th>Score</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><strong>Vector Score</strong></td>
    <td>Relative similarity from Couchbase FTS vector search</td>
  </tr>
  <tr>
    <td><strong>Semantic Score</strong></td>
    <td>LLM-based reranking relevance score</td>
  </tr>
  <tr>
    <td><strong>Threshold</strong></td>
    <td>Minimum score required to avoid LLM fallback</td>
  </tr>
</table>

<hr/>

<h2>🧪 Why This Matters</h2>

<p>
This project demonstrates how to build <strong>controlled, explainable AI systems</strong>:
</p>

<ul>
  <li>Prevent unnecessary LLM usage</li>
  <li>Eliminate hallucinated authority</li>
  <li>Combine probabilistic search with deterministic rules</li>
  <li>Enable agent toolchains safely</li>
  <li>Operate AI with <em>confidence</em>, not vibes</li>
</ul>

<hr/>

<h2>🧩 Agent-Ready Design</h2>

<p>
This system can be exposed as a <strong>tool</strong> to:
</p>

<ul>
  <li>LangChain agents</li>
  <li>Bedrock Agents</li>
  <li>Custom orchestration frameworks</li>
</ul>

<p>
Because results are scored, audited, and bounded, agents can:
</p>

<ul>
  <li>Trust responses</li>
  <li>Inspect provenance</li>
  <li>Decide whether escalation is required</li>
</ul>

<hr/>

<h2>📁 Project Structure</h2>

<pre>
hash_agentcatalog.py   # End-to-end pipeline + UI
requirements.txt       # Python dependencies
README.md              # This document
</pre>

<hr/>

<h2>📜 License</h2>

<p>
MIT License — use freely, responsibly, and visibly.
</p>

<hr/>

<h2>🙌 Credits</h2>

<p>
Built with:
</p>

<ul>
  <li>Couchbase Vector Search</li>
  <li>AWS Bedrock</li>
  <li>Streamlit</li>
  <li>Python</li>
</ul>

<p>
Designed for engineers who want <strong>control</strong>, not magic.
</p>

</body>
</html>

<hr/>

<h2>🔄 Decision Pipeline Flow</h2>

<p>
The diagram below illustrates how every request flows through the system,
with deterministic gates controlling when (and if) an LLM is allowed to run.
</p>

<div style="text-align: center; margin: 30px 0;">
  <img
    src="/images/pipeline-flow.png"
    alt="Agent Catalog Decision Pipeline"
    style="max-width: 100%; border: 1px solid #ddd; border-radius: 6px;"
  />
</div>

<p>
<strong>Key principle:</strong> LLMs are used <em>only</em> when cheaper, more deterministic
retrieval layers fail to meet confidence thresholds.
</p>
