"""
Customer Support AI Agent
=========================
A production-grade customer support assistant built with Amazon Bedrock AgentCore
and the Strands SDK. Handles order tracking, refund processing, product/policy RAG,
cross-session persistent memory, loyalty discount calculations, and live web browsing.
"""
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json, os, asyncio, boto3, logging, uuid, traceback
from strands.hooks import HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

app = BedrockAgentCoreApp()
os.environ["BYPASS_TOOL_CONSENT"] = "true"

# AWS & Bedrock AgentCore Configuration
GATEWAY_URL = "https://customersupportgateway-0vqewifwth.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "7D3J0ZWPXJ"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-85Q7wnDxyO"

model_id = "global.amazon.nova-2-lite-v1:0"
model = BedrockModel(model_id=model_id)
memory_client = MemoryClient(region_name=REGION)
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """
    Fetch strategy types and namespace templates from the memory resource,
    supporting both 'namespaceTemplates' and legacy 'namespaces' fields.
    """
    strategies = mem_client.get_memory_strategies(memory_id)
    return {
        strategy["type"]: strategy.get("namespaceTemplates", strategy.get("namespaces", []))[0]
        for strategy in strategies
    }


class MemoryHook(HookProvider):
    """
    AgentCore Memory hook provider for managing cross-session conversation context.
    Retrieves semantic facts and preferences before model invocation and persists
    plain-text interaction turns to long-term memory afterwards.
    """
    def __init__(self, actor_id: str, session_id: str, memory_client: MemoryClient, memory_id: str):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(memory_client, memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Prepend relevant customer facts and preferences to the latest user message."""
        if not event.agent.messages:
            return

        last_msg = event.agent.messages[-1]

        if isinstance(last_msg, dict):
            role = last_msg.get("role")
            content = last_msg.get("content", [])
        else:
            role = getattr(last_msg, "role", None)
            content = getattr(last_msg, "content", [])

        # Only inject context into incoming user prompts, not tool responses or assistant turns
        if role != "user":
            return

        query_text = ""
        if isinstance(content, str):
            query_text = content
        elif isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                # Avoid treating toolResult payload as user query
                if "toolResult" in first or first.get("type") == "tool_result":
                    return
                query_text = first.get("text", "")
            else:
                query_text = getattr(first, "text", "")

        if not query_text:
            return

        context_blocks = []

        for strat_type, namespace_template in self.namespaces.items():
            ns = namespace_template.format(actorId=self.actor_id)
            try:
                mems = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    memory_namespace=ns,
                    query=query_text,
                    top_k=5
                )

                for m in mems:
                    text = ""
                    if isinstance(m, dict):
                        text = m.get("text") or m.get("content") or ""
                    else:
                        text = getattr(m, "text", getattr(m, "content", ""))
                    if text:
                        context_blocks.append(f"[{strat_type}] {text}")

            except Exception as e:
                logger.warning(f"Error retrieving memory for {strat_type}: {e}")

        if context_blocks:
            mem_str = "\n".join(context_blocks)
            context_text = f"Customer Context:\n{mem_str}\n\n{query_text}"

            if isinstance(last_msg, dict):
                if last_msg.get("content") and isinstance(last_msg["content"][0], dict):
                    last_msg["content"][0]["text"] = context_text
            else:
                last_msg.content[0].text = context_text

    def save_support_interaction(self, event: AfterInvocationEvent):
        """
        Extract the latest plain-text user query and assistant answer,
        strictly filtering out tool results, and persist to AgentCore Memory.
        """
        def extract_plain_text(msg):
            if not msg:
                return ""
            content = msg.get("content", []) if isinstance(msg, dict) else getattr(msg, "content", [])
            if isinstance(content, str):
                return content
            texts = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        # Filter out tool execution payloads
                        if "toolResult" in item or item.get("type") == "tool_result":
                            continue
                        if "toolUse" in item or item.get("type") == "tool_use":
                            continue
                        if "text" in item and item["text"]:
                            texts.append(item["text"])
                    elif hasattr(item, "text") and item.text:
                        texts.append(item.text)
            return " ".join(texts).strip()

        user_text = None
        assistant_text = None

        # Scan backwards to get the most recent genuine user input and assistant output
        for msg in reversed(event.agent.messages):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            text = extract_plain_text(msg)
            if not text:
                continue

            if role == "assistant" and assistant_text is None:
                assistant_text = text
            elif role == "user" and user_text is None:
                # Remove injected customer context prefix if present
                if "Customer Context:\n" in text and "\n\n" in text:
                    text = text.split("\n\n")[-1].strip()
                user_text = text

            if user_text and assistant_text:
                break

        if user_text and assistant_text:
            try:
                self.memory_client.create_event(
                    memory_id=self.memory_id,
                    actor_id=self.actor_id,
                    session_id=self.session_id,
                    messages=[
                        (user_text, "USER"),
                        (assistant_text, "ASSISTANT")
                    ]
                )
            except Exception as e:
                logger.warning(f"Error persisting interaction event: {e}")

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    
    Call this tool when the customer asks about:
    - Product specifications, features, warranty, pricing, and availability
    - Store policies including return policies, return windows, and refund rules
    - Shipping options, delivery timelines, and carrier information
    - Loyalty rewards program tiers, benefits, and membership perks
    
    Do NOT call this tool for tracking specific customer order IDs or general ungrounded web questions.

    Args:
        query: The search query string representing the customer's policy or product question.
    """
    try:
        if not KB_ID:
            return "Knowledge Base ID is not configured."
        resp = _bedrock_runtime.retrieve(knowledgeBaseId=KB_ID, retrievalQuery={"text": query})
        results = resp.get("retrievalResults", [])
        if not results:
            return "No relevant information found."
        return "\n---\n".join([r["content"]["text"] for r in results])
    except Exception as e:
        return f"Error: {e}"


@tool
def calculate_loyalty_discount(loyalty_points: int, tier: str, order_total: float, product_category: str = "standard") -> str:
    """
    Calculate the loyalty discount for a customer order using the AgentCore Code Interpreter.
    Encodes business rules for points redemption, tier discounts, and category earn rates.
    """
    code = f'''
earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}
loyalty_points = {loyalty_points}
tier = "{tier}"
order_total = {order_total}
product_category = "{product_category}"
points_redeemed = (loyalty_points // 500) * 500
if (points_redeemed / 100) > (order_total / 2):
    points_redeemed = int((order_total / 2) * 100)
    points_redeemed = (points_redeemed // 500) * 500
points_discount = points_redeemed / 100.0
subtotal = order_total - points_discount
tier_discount = subtotal * tier_rates.get(tier, 0.0)
final_total = subtotal - tier_discount
points_earned = int(final_total * earn_rates.get(product_category, 1))
tier_discount_pct = tier_rates.get(tier, 0.0) * 100
import json
print(json.dumps({{"points_redeemed": points_redeemed, "points_discount": points_discount, "tier_discount": round(tier_discount, 2), "tier_discount_pct": tier_discount_pct, "final_total": round(final_total, 2), "points_earned": points_earned, "remaining_points": loyalty_points - points_redeemed + points_earned}}))
'''
    try:
        cs = code_session(REGION)
        result = cs.invoke("executeCode", language="python", code=code, clearContext=True)
        return result[0].get("text", "{}") if result else "{}"
    except Exception as e:
        # Robust fallback returning the exact full schema required by the contract
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier, 0.0)
        tier_discount_pct = tier_rate * 100.0

        points_redeemed = (loyalty_points // 500) * 500
        if (points_redeemed / 100.0) > (order_total / 2.0):
            points_redeemed = int((order_total / 2.0) * 100)
            points_redeemed = (points_redeemed // 500) * 500

        points_discount = points_redeemed / 100.0
        subtotal = max(0.0, order_total - points_discount)
        tier_discount = subtotal * tier_rate
        final_total = max(0.0, subtotal - tier_discount)
        earn_rates = {"standard": 1, "device": 2, "fresh": 5}
        points_earned = int(final_total * earn_rates.get(product_category, 1))
        remaining_points = loyalty_points - points_redeemed + points_earned

        return json.dumps({
            "points_redeemed": points_redeemed,
            "points_discount": round(points_discount, 2),
            "tier_discount": round(tier_discount, 2),
            "tier_discount_pct": tier_discount_pct,
            "final_total": round(final_total, 2),
            "points_earned": points_earned,
            "remaining_points": remaining_points,
            "note": "Fallback calculation"
        })


@app.entrypoint
async def invoke(payload, context=None):
    """Main handler called by AgentCore Runtime"""
    prompt = payload.get("prompt", "")
    actor_id = payload.get("customer_id", "anonymous")
    session_id = payload.get("session_id", str(uuid.uuid4()))
    
    hooks = [MemoryHook(actor_id, session_id, memory_client, MEMORY_ID)]
    agent_core_browser = AgentCoreBrowser(region=REGION)
    tools = [search_knowledge_base, calculate_loyalty_discount, agent_core_browser.browser]
    
    try:
        transport = lambda: streamable_http_client(url=GATEWAY_URL)
        mcp = MCPClient(transport_callable=transport)
        
        gateway_tools = await mcp.load_tools()
        tools.extend(gateway_tools)
        
        agent = Agent(
            model=model,
            system_prompt="You are an expert customer support agent for Amazon. Be helpful and concise.",
            tools=tools,
            hooks=hooks
        )
        response = await agent.invoke_async(prompt)
        
        if hasattr(response, "message") and isinstance(response.message, dict):
            return response.message.get("content", [{}])[0].get("text", "")
        else:
            return response.messages[-1].content[0].text
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"I apologize, but I encountered an internal error. (Error details: {str(e)})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    try:
        response = asyncio.run(invoke(json.loads(args.payload)))
        print(response)
        print("\n")
    except Exception:
        pass
    import os
    os._exit(0)


if __name__ == "__main__":
    app.run()
    # For local CLI testing:
    # main()
