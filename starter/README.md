# Customer Support Agent Project

This is my project for the Udacity AI course. It is a customer support bot built with Amazon Bedrock AgentCore and the Strands SDK.

The bot can do a few things:
* Check order status and process refunds by talking to AWS Lambda functions through an MCP Gateway.
* Answer policy questions using a Bedrock Knowledge Base.
* Remember what you said earlier in the conversation using AgentCore Memory.
* Calculate loyalty discounts using a python code sandbox.
* Browse the web to get live info.

### How to run it
Since the agentcore cli got updated and didn't have the configure command anymore, I ran the tests locally using this command:

```
python -m uv run main.py '{"prompt": "Where is my order ORD-001?", "customer_id": "CUST-123", "session_id": "test1"}'
```

### Files included
* main.py: the main agent code
* lambda/order_tracker.py and lambda/refund_processor.py: the backend apis
* reflection.txt: my notes on the project
* screenshots/: the test outputs
