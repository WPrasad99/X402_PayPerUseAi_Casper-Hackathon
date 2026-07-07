"""
AI Execution Gateway — Central orchestrator for marketplace AI requests.

Security model:
- User session/payment validated BEFORE any AI execution
- Creator API keys decrypted ONLY during execution, never cached
- Provider adapters instantiated per-request with creator's key
- Usage logged with proof hashes for on-chain verification
- Revenue split: 90% creator / 10% platform

BYOK is MANDATORY — creators must provide their own API keys.
"""
import hashlib
from typing import AsyncIterator, Union

from app.core.encryption import decrypt_api_key
from app.config import settings
from app import database as db


# Provider adapter registry
PROVIDER_MAP = {
    "openai": ("app.services.providers.openai_provider", "OpenAIProvider"),
    "groq": ("app.services.providers.groq_provider", "GroqProvider"),
    "gemini": ("app.services.providers.gemini_provider", "GeminiProvider"),
    "huggingface": ("app.services.providers.hf_provider", "HuggingFaceProvider"),
}


def _get_provider_class(provider_name: str):
    """Dynamically import and return the provider class."""
    if provider_name not in PROVIDER_MAP:
        raise ValueError(f"Unsupported provider: {provider_name}")
    module_path, class_name = PROVIDER_MAP[provider_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _hash_content(content: str) -> str:
    """SHA-256 hash for proof-of-intelligence."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


async def execute_agent_chat(
    agent_id: str,
    user_wallet: str,
    messages: list[dict],
) -> AsyncIterator[Union[str, dict]]:
    """
    Execute an AI agent chat request through the secure gateway.

    Flow:
    1. Load agent config from DB
    2. Decrypt creator's API key
    3. Instantiate correct provider adapter
    4. Stream response
    5. Calculate token usage + cost
    6. Record usage + revenue split in DB
    7. Yield response chunks

    Raises:
        ValueError: If agent not found, inactive, or no API key
        RuntimeError: If provider execution fails
    """
    # 1. Load agent config
    agent = await db.get_ai_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")
    if not agent['is_active']:
        raise ValueError("Agent is no longer active")

    creator_wallet = agent['creator_wallet']
    provider_name = agent['provider']

    # 2. Decrypt creator's API key (BYOK mandatory)
    encrypted_key = await db.get_creator_api_key(creator_wallet, provider_name)
    if not encrypted_key:
        raise ValueError(
            f"Creator has not configured a {provider_name} API key. "
            "Creators must bring their own API keys (BYOK)."
        )

    try:
        api_key = decrypt_api_key(encrypted_key).strip().replace('"', '').replace("'", "")
    except Exception as e:
        raise RuntimeError(f"Failed to decrypt creator API key: {e}")

    # 3. Instantiate provider adapter
    ProviderClass = _get_provider_class(provider_name)
    model_name = agent['model']
    if model_name == 'gemini-2.0-flash':
        model_name = 'gemini-1.5-flash'
        
    provider = ProviderClass(
        api_key=api_key,
        model=model_name,
        system_prompt=agent['system_prompt'],
        temperature=agent.get('temperature', 0.7),
        max_tokens=agent.get('max_tokens', 1500),
    )

    # 4. Stream response and collect usage
    full_response = ""
    usage_info = None

    async def _stream_and_collect():
        nonlocal full_response, usage_info
        async for chunk in provider.stream_chat(messages):
            if isinstance(chunk, dict):
                usage_info = chunk
            else:
                full_response += chunk
                yield chunk

        # 5. After streaming completes, calculate cost and record usage
        if usage_info:
            input_tokens = usage_info.get("input_tokens", 0)
            output_tokens = usage_info.get("output_tokens", 0)
        else:
            # Fallback estimation
            import json
            input_tokens = len(json.dumps(messages)) // 4
            output_tokens = len(full_response) // 4

        total_tokens = input_tokens + output_tokens

        # Calculate cost based on pricing model
        if user_wallet == creator_wallet:
            cost_motes = 0
        elif agent.get('pricing_model') == 'per_request':
            cost_motes = agent.get('price_per_request_motes', 0)
        else:
            # Per-token pricing
            input_cost = (input_tokens * agent.get('price_input_motes', 0)) // 1_000_000
            output_cost = (output_tokens * agent.get('price_output_motes', 0)) // 1_000_000
            cost_motes = input_cost + output_cost

        # Revenue split: 90% creator, 10% platform
        fee_pct = settings.marketplace_fee_pct
        platform_cut = (cost_motes * fee_pct) // 100
        creator_cut = cost_motes - platform_cut

        # Create proof hashes
        prompt_text = messages[-1]['content'] if messages else ''
        prompt_hash = _hash_content(prompt_text)
        response_hash = _hash_content(full_response)

        # 6. Record everything in DB
        try:
            await db.log_agent_usage(
                agent_id=agent_id,
                user_wallet=user_wallet,
                prompt_hash=prompt_hash,
                response_hash=response_hash,
                tokens_input=input_tokens,
                tokens_output=output_tokens,
                cost_motes=cost_motes,
                creator_cut_motes=creator_cut,
                platform_cut_motes=platform_cut,
            )
            await db.increment_agent_usage(agent_id, total_tokens, cost_motes)
            if cost_motes > 0:
                await db.log_creator_earning(creator_wallet, agent_id, creator_cut, 'earning')
                await db.update_creator_earnings_total(creator_wallet, creator_cut)
            
            # NOTE: On-chain settlement (previously Algorand) is now handled via the X402 middleware
            # abstracting it into off-chain session balances that deduct asynchronously.
        except Exception as e:
            print(f"Error during usage logging/settlement: {e}")

        # Yield final usage info
        yield {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_motes": cost_motes,
            "creator_cut_motes": creator_cut,
            "platform_cut_motes": platform_cut,
            "prompt_hash": prompt_hash,
            "response_hash": response_hash,
        }

    async for item in _stream_and_collect():
        yield item
