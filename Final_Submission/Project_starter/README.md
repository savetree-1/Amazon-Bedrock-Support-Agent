# AI Customer Support Agent with Amazon Bedrock AgentCore & Strands SDK

A production-grade, multi-turn AI customer support assistant built for an e-commerce platform using **Amazon Bedrock AgentCore** and the **Strands SDK**. The agent integrates order tracking, returns processing, product and policy Retrieval-Augmented Generation (RAG), persistent cross-session memory, sandboxed code interpretation, and real-time web browsing into a unified conversational interface.

---

## 🏗️ Architecture & Core Integrations

1. **AgentCore Cloud Runtime**:
   - Hosted via `BedrockAgentCoreApp` with `@app.entrypoint` decorator and `app.run()` main entrypoint.
   - Powered by Amazon Nova Lite (`amazon.nova-2-lite-v1:0`).

2. **Model Context Protocol (MCP) Gateway**:
   - Connects to an AgentCore Gateway (`CustomerSupportGateway`) using `MCPClient` and `streamable_http_client`.
   - Exposes backend tools:
     - **Order Tracking API Target**: `order-tracker___get_order`, `order-tracker___get_customer_orders`, `order-tracker___get_customer` (API Gateway REST Proxy to Lambda).
     - **Refund Processor Target**: `refund-processor___initiate_refund`, `refund-processor___check_refund_status`, `refund-processor___get_return_label` (Direct Lambda invocation).

3. **Knowledge Base RAG (`search_knowledge_base`)**:
   - Connected to Amazon Bedrock Managed Knowledge Base (`CustomerSupportKB`).
   - Retrieves grounded product catalog data and official support policies (e.g., 15-day return window for electronics, Prime perks, warranties).
   - Guarded with configuration checks and specific docstrings for tool routing.

4. **Persistent Cross-Session Memory (`MemoryHook`)**:
   - Uses `BedrockAgentCoreApp` and `MemoryClient` with semantic extraction and user preference strategies.
   - `retrieve_customer_context`: Extracts namespaces using `namespaceTemplates` / `namespaces`, fetches semantic memories, and prepends them as `Customer Context:` before generation.
   - `save_support_interaction`: Recursively extracts pure plain-text customer queries (filtering out intermediate `toolResult` and `toolUse` blocks) and assistant responses to persist interactions via `create_event()`.

5. **Sandboxed Code Interpreter (`calculate_loyalty_discount`)**:
   - Executes exact arithmetic and tier-based business logic via `code_session.invoke("executeCode", clearContext=True)`.
   - Fully resilient fallback returning all mandatory contract fields: `points_redeemed`, `tier_discount_pct`, `final_total`, and `remaining_points`.

6. **Live Web Browsing (`AgentCoreBrowser`)**:
   - Instantiates `AgentCoreBrowser` to fetch and verify live web pages.

---

## 🚀 Deployment & Invocation

### 1. Configure and Deploy
```bash
# Configure the agent deployment
uv run agentcore configure --entrypoint main.py --name support-agent --deployment-type direct_code_deploy --runtime PYTHON_3_13 --disable-memory

# Deploy to Amazon Bedrock AgentCore Runtime
uv run agentcore deploy

# Wire up IAM permissions for Knowledge Base, Memory, and Browser
uv run setup_permissions.py
```

### 2. Invoke via AgentCore CLI
```bash
agentcore invoke '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t1"}'
```

*(Note: Local testing can also be run using `python -m uv run main.py '{"prompt": "..."}'`)*

---

## 📋 Verification & Test Conversation Logs

| Test | Objective | Target / Tool | Command & Result |
| :--- | :--- | :--- | :--- |
| **Test 1** | Order Tracking | `order-tracker___get_order` | `ORD-001` status: **SHIPPED**, Carrier: UPS, Tracking: TRK987654321, Delivery: Sep 19, 2026. |
| **Test 2** | Refund Processing | `refund-processor` | Checks status of `REF-123`: Status: **PROCESSING**, estimated 2-3 business days. |
| **Test 3** | Knowledge Base RAG | `search_knowledge_base` | Return policy for electronics: 15-day window, original condition, free for Prime members. |
| **Test 4** | Cross-Session Memory | `MemoryHook` | **Session 1:** User mentions buying TV for daughter Maya.<br>**Session 2:** Recall confirmed — recalls "daughter, Maya". |
| **Test 5** | Loyalty Discount | `calculate_loyalty_discount` | $150 standard order with 1200 points (Gold): 1,000 pts redeemed ($10 off), 10% Gold tier ($14 off), final total: $126.00, remaining points: 326. |
| **Test 6** | Browser Tool | `AgentCoreBrowser` | Navigates to `example.com` and accurately retrieves heading `"Example Domain"`. |

---

## 📁 Repository Structure

```
.
├── Final_Submission/
│   └── Project_starter/
│       ├── lambda/
│       │   ├── lambda_schema
│       │   ├── order_tracker.py
│       │   └── refund_processor.py
│       ├── screenshots/
│       │   ├── test1_order_tracking.png
│       │   ├── test2_refund_processing.png
│       │   ├── test3_knowledge_base.png
│       │   ├── test4_memory.png
│       │   ├── test5_loyalty_discount.png
│       │   ├── test6_browser.png
│       │   └── agentcore_invoke_evidence.png
│       ├── main.py
│       ├── setup_permissions.py
│       ├── product_catalog.txt
│       ├── pyproject.toml
│       ├── reflection.txt
│       └── README.md
├── starter/
│   ├── lambda/
│   ├── screenshots/
│   ├── main.py
│   ├── setup_permissions.py
│   ├── product_catalog.txt
│   ├── pyproject.toml
│   ├── REFLECTION.md
│   ├── reflection.txt
│   └── README.md
└── README.md
```
