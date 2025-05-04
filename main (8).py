import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,  # Changed from Application.builder()
    CommandHandler,
    Application,
    MessageHandler, 
    filters, 
    ContextTypes, 
    ConversationHandler
)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# States for conversation
WALLET = 0

# Sui RPC endpoint
SUI_RPC_URL = "https://fullnode.mainnet.sui.io:443"

# Price API endpoint (CoinGecko)
PRICE_API_URL = "https://api.coingecko.com/api/v3/simple/price"

# Explorer URLs
SUISCAN_URL = "https://suiscan.xyz/mainnet/account/"
SUIVISION_URL = "https://suivision.xyz/account/"

# Function to get SUI price and known token prices
async def get_token_prices():
    try:
        # Get SUI price from CoinGecko
        params = {
            "ids": "sui",
            "vs_currencies": "usd"
        }
        
        response = requests.get(PRICE_API_URL, params=params)
        data = response.json()
        
        prices = {
            "0x2::sui::SUI": data.get("sui", {}).get("usd", 0)
        }
        
        # Add other known token prices here
        # In a production environment, you would have a more comprehensive token price database
        # This is a simplified example with just SUI
        
        return prices
    except Exception as e:
        logger.error(f"Error fetching token prices: {str(e)}")
        return {"0x2::sui::SUI": 0}

# Function to fetch wallet balance
async def get_wallet_balance(wallet_address):
    try:
        # First check all coins
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getAllCoins",
            "params": [wallet_address, None, 50]
        }
        
        response = requests.post(SUI_RPC_URL, json=payload)
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            sui_balance = 0
            
            # Find SUI coins and sum their balances
            for coin in data["result"]["data"]:
                if coin["coinType"] == "0x2::sui::SUI":
                    sui_balance += int(coin["balance"])
            
            # Get SUI price
            token_prices = await get_token_prices()
            sui_price = token_prices.get("0x2::sui::SUI", 0)
            sui_value_usd = (sui_balance / 1_000_000_000) * sui_price
            
            return {
                "coin": "SUI",
                "balance": sui_balance / 1_000_000_000,  # Convert from MIST to SUI
                "value_usd": sui_value_usd,
                "error": None
            }
        else:
            # Fallback to getBalance if getAllCoins fails
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "suix_getBalance",
                "params": [wallet_address, "0x2::sui::SUI"]
            }
            
            response = requests.post(SUI_RPC_URL, json=payload)
            data = response.json()
            
            if "result" in data:
                # Get SUI price
                token_prices = await get_token_prices()
                sui_price = token_prices.get("0x2::sui::SUI", 0)
                balance = int(data["result"]["totalBalance"]) / 1_000_000_000
                sui_value_usd = balance * sui_price
                
                return {
                    "coin": "SUI",
                    "balance": balance,
                    "value_usd": sui_value_usd,
                    "error": None
                }
            else:
                return {"error": "Failed to fetch balance", "data": data}
    except Exception as e:
        return {"error": f"Error fetching balance: {str(e)}"}

# Function to fetch wallet's owned objects (tokens)
async def get_wallet_tokens(wallet_address):
    try:
        all_tokens = {}
        cursor = None
        total_count = 0
        total_value_usd = 0
        
        # Get token prices
        token_prices = await get_token_prices()
        
        # Get all coins first
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getAllCoins",
            "params": [wallet_address, None, 100]
        }
        
        response = requests.post(SUI_RPC_URL, json=payload)
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            for coin in data["result"]["data"]:
                token_type = coin["coinType"].split("::")[-1]
                full_type = coin["coinType"]
                balance = int(coin["balance"])
                
                # Calculate USD value if price is available
                token_price = token_prices.get(full_type, 0)
                if full_type == "0x2::sui::SUI":
                    value_usd = (balance / 1_000_000_000) * token_price
                    balance_formatted = balance / 1_000_000_000  # Convert MIST to SUI
                else:
                    value_usd = 0  # For other tokens, we'd need their specific conversion rates
                    balance_formatted = balance
                
                if full_type not in all_tokens:
                    all_tokens[full_type] = {
                        "name": token_type,
                        "count": 0,
                        "balance": 0,
                        "balance_formatted": 0,
                        "value_usd": 0
                    }
                
                all_tokens[full_type]["count"] += 1
                all_tokens[full_type]["balance"] += balance
                all_tokens[full_type]["balance_formatted"] += balance_formatted
                all_tokens[full_type]["value_usd"] += value_usd
                total_value_usd += value_usd
            
            total_count += len(data["result"]["data"])
        
        # Also get NFTs and other objects
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getOwnedObjects",
            "params": [wallet_address, None, None, 50]
        }
        
        response = requests.post(SUI_RPC_URL, json=payload)
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            for obj in data["result"]["data"]:
                if "type" in obj["data"]:
                    obj_type = obj["data"]["type"]
                    
                    # Skip coins as we already processed them
                    if "::coin::Coin<" in obj_type:
                        continue
                        
                    type_parts = obj_type.split("::")
                    if len(type_parts) > 1:
                        token_type = type_parts[-1]
                        if "<" in token_type:
                            token_type = token_type.split("<")[0]
                        
                        if obj_type not in all_tokens:
                            all_tokens[obj_type] = {
                                "name": token_type,
                                "count": 0,
                                "balance": None,  # Not a coin, so no balance
                                "balance_formatted": None,
                                "value_usd": 0  # NFTs would need price lookup
                            }
                        
                        all_tokens[obj_type]["count"] += 1
                        total_count += 1
            
        return {
            "tokens": all_tokens, 
            "count": total_count, 
            "total_value_usd": total_value_usd,
            "error": None
        }
    except Exception as e:
        return {"error": f"Error fetching tokens: {str(e)}"}

# Function to fetch wallet activity
async def get_wallet_activity(wallet_address):
    try:
        # Try getting transactions sent from this address
        from_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_queryTransactionBlocks",
            "params": [
                {"FromAddress": wallet_address},
                {"limit": 30, "descendingOrder": True},
                None
            ]
        }
        
        from_response = requests.post(SUI_RPC_URL, json=from_payload)
        from_data = from_response.json()
        
        # Also try getting transactions to this address
        to_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "suix_queryTransactionBlocks",
            "params": [
                {"ToAddress": wallet_address},
                {"limit": 30, "descendingOrder": True},
                None
            ]
        }
        
        to_response = requests.post(SUI_RPC_URL, json=to_payload)
        to_data = to_response.json()
        
        from_count = 0
        to_count = 0
        
        if "result" in from_data and "data" in from_data["result"]:
            from_count = len(from_data["result"]["data"])
        
        if "result" in to_data and "data" in to_data["result"]:
            to_count = len(to_data["result"]["data"])
        
        total_txs = from_count + to_count
        
        # Determine activity level based on transaction count
        # Updated logic based on your requirements
        if total_txs == 0:
            activity_level = "Inactive"
        elif total_txs < 10:
            activity_level = "Low"
        elif total_txs < 50:
            activity_level = "Moderate"
        else:
            activity_level = "High"
        
        return {
            "outgoing_txs":from_count,
            "incoming_txs": to_count,
            "recent_transactions": total_txs,
            "activity_level": activity_level,
            "error": None
        }
    except Exception as e:
        return {"error": f"Error fetching activity: {str(e)}"}

# Help command handler

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_message = (
        "📚 *NeptuneSui Onchain Bot - Help Guide* 📚\n\n"
        "*Available Commands:*\n\n"
        "🔹 `/check <address>`\n"
        "   Get a complete overview of your wallet\n"
        "   Shows balance, activity level, and token count\n\n"
        "🔹 `/token <address>(development almost complete)`\n"
        "   View detailed token holdings\n"
        "   Displays coins, NFTs, and estimated values\n\n"
        "🔹 `/token_info <token_address>(STILL IN DEVELOPMENT)`\n"
        "   Analyze a specific token contract\n"
        "   Shows supply, holders, and activity metrics\n\n"
        "🔹 `/help`\n"
        "   Shows this help message\n\n"
        "*Examples:*\n"
        "• `/check 0x1234...abcd`\n"
        "• `/token 0x1234...abcd`\n"
        "• `/token_info 0x2::sui::SUI`"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🔍 Check Wallet", url="https://suiscan.xyz/"),
            InlineKeyboardButton("🪙 View Tokens", url="https://suiscan.xyz/")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(help_message, parse_mode='Markdown', reply_markup=reply_markup)

# Updated Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Create a more visually appealing welcome message
    welcome_message = (
        "🌟 *Welcome to Neptune Sui Onchain Bot!* 🧜‍♂️\n\n"
        "Get Onchain information for Sui wallet address, tokens, and activity with ease!\n\n"
        "📱 *Available Commands:*\n"
        "• `/check <address>` - Get wallet overview and stats\n"
        "• `/token <address>` - See detailed token holdings\n"
        "• `/token_info <token_address>` - Analyze token contracts\n"
        "• `/help` - Display this help message\n\n"
        "🔍 *Try it now:* Send `/check` followed by your Sui wallet address\n"
        "Example: `/check 0x123abc...`\n\n"
        "The `/token_info` command isnt working ATM❌ and the dollar value of memecoins other than sui might not be correct, everything will be fixed before Wednesday and bot will be fully functional 🧜‍♂️\n\n"
        "Join our community @neptunesui"
    )
    
    # Create keyboard with useful links
    keyboard = [
        [
            InlineKeyboardButton("✨ Visit Sui Explorer", url="https://suiscan.xyz/"),
            InlineKeyboardButton("📚 Sui Official", url="https://sui.io/")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
    
# Determine activity level based on both transactions and token count
def determine_activity_level(transaction_count, token_count):
    # Transaction-based activity
    if transaction_count == 0:
        tx_activity = "Inactive"
    elif transaction_count < 10:
        tx_activity = "Low"
    elif transaction_count < 50:
        tx_activity = "Moderate"
    else:
        tx_activity = "High"
    
    # Token-based activity
    if token_count == 0:
        token_activity = "Inactive"
    elif token_count < 5:
        token_activity = "Low"
    elif token_count < 20:
        token_activity = "Moderate"
    else:
        token_activity = "High"
    
    # Combine both metrics - prioritize the higher activity level
    activity_levels = {"Inactive": 0, "Low": 1, "Moderate": 2, "High": 3}
    
    tx_level = activity_levels[tx_activity]
    token_level = activity_levels[token_activity]
    
    combined_level = max(tx_level, token_level)
    
    # Convert back to string
    activity_mapping = {0: "Inactive", 1: "Low", 2: "Normal", 3: "Moderate"}
    return activity_mapping[combined_level]

# Get activity emoji based on level
def get_activity_emoji(level):
    emoji_map = {
        "Inactive": "⚪",
        "Low": "🟠",
        "Normal": "🟢",
        "Moderate": "🟢🟢"
    }
    return emoji_map.get(level, "⚪")

# Check wallet stats
async def check_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get wallet address from command arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "🔍 *Please provide a Sui wallet address*\n\n"
            "Example: `/check 0x123...`\n\n"
            "Type your wallet address after the command to view your stats.",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0]
    
    # Validate address format
    if not wallet_address.startswith("0x") or len(wallet_address) < 10:
        await update.message.reply_text(
            "❌ *Invalid Sui wallet address format*\n\n"
            "Make sure your address starts with '0x' and is the correct length.\n"
            "Try again with a valid address.",
            parse_mode='Markdown'
        )
        return
    
    # Show a simple loading message
    await update.message.reply_text(f"🔍 Checking wallet {wallet_address}...")
    
    # Fetch wallet data
    balance_data = await get_wallet_balance(wallet_address)
    activity_data = await get_wallet_activity(wallet_address)
    tokens_data = await get_wallet_tokens(wallet_address)
    
    # Determine combined activity level
    token_count = tokens_data.get("count", 0) if not tokens_data.get("error") else 0
    transaction_count = activity_data.get("recent_transactions", 0) if not activity_data.get("error") else 0
    
    activity_level = determine_activity_level(transaction_count, token_count)
    activity_emoji = get_activity_emoji(activity_level)
    
    # Build explorer links
    suiscan_link = f"{SUISCAN_URL}{wallet_address}"
    suivision_link = f"{SUIVISION_URL}{wallet_address}"
    
    # Create keyboard with explorer links
    keyboard = [
        [
            InlineKeyboardButton("🔍 SuiScan Explorer", url=suiscan_link),
            InlineKeyboardButton("📊 SuiVision", url=suivision_link)
        ],
        [
            InlineKeyboardButton("🪙 View Tokens", url=f"{SUISCAN_URL}{wallet_address}#tokens")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format response
    response = f"📊 *SUI WALLET ANALYSIS* 📊\n"
    response += f"━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"*Address:* `{wallet_address[:6]}...{wallet_address[-4:]}`\n\n"
    
    # Add balance information
    if balance_data.get("error"):
        response += f"💰 *Balance:* Unable to fetch balance\n"
    else:
        sui_value = balance_data.get("value_usd", 0)
        response += f"💰 *Balance:* {balance_data['balance']:.6f} SUI\n"
        response += f"💵 *Value:* ${sui_value:.2f} USD\n"
    
    response += f"\n"
    
    # Add activity information
    if activity_data.get("error") and "No transactions found" not in activity_data.get("error", ""):
        response += f"🔄 *Activity:* Unable to fetch activity\n"
    else:
        in_txs = activity_data.get("incoming_txs", 0)
        out_txs = activity_data.get("outgoing_txs", 0)
        total_txs = activity_data.get("recent_transactions", 0)
        
        response += f"🔄 *Activity Level:* {activity_emoji} {activity_level}\n"
        response += f"📥 *Incoming:* {in_txs} transactions\n"
        response += f"📤 *Outgoing:* {out_txs} transactions\n"
    
    response += f"\n"
    
    # Add token information
    if tokens_data.get("error"):
        response += f"🪙 *Tokens:* Unable to fetch tokens\n"
    else:
        total_value = tokens_data.get("total_value_usd", 0)
        response += f"🪙 *Total Tokens:* {tokens_data['count']} tokens/objects\n"
        response += f"💵 *Portfolio Value:* ${total_value:.2f} USD\n"
    
    response += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"Use `/token {wallet_address}` for detailed token breakdown"
    
    # Send the final response
    await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reply_markup)

# Token command handler
async def token_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get wallet address from command arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "🪙 *Please provide a Sui wallet address*\n\n"
            "Example: `/token 0x123...`\n\n"
            "Type your wallet address after the command to view your tokens.",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0]
    
    # Validate address format
    if not wallet_address.startswith("0x") or len(wallet_address) < 10:
        await update.message.reply_text(
            "❌ *Invalid Sui wallet address format*\n\n"
            "Make sure your address starts with '0x' and is the correct length.\n"
            "Try again with a valid address.",
            parse_mode='Markdown'
        )
        return
    
    # Show a simple loading message
    await update.message.reply_text(f"🔍 Fetching tokens for {wallet_address}...")
    
    # Fetch wallet tokens
    tokens_data = await get_wallet_tokens(wallet_address)
    
    # Build explorer links
    suiscan_link = f"{SUISCAN_URL}{wallet_address}"
    suivision_link = f"{SUIVISION_URL}{wallet_address}"
    
    # Create keyboard with explorer links
    keyboard = [
        [
            InlineKeyboardButton("🔍 View on SuiScan", url=suiscan_link),
            InlineKeyboardButton("📊 View on SuiVision", url=suivision_link)
        ],
        [
            InlineKeyboardButton("🔄 Check Wallet Stats", url=f"{SUISCAN_URL}{wallet_address}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if tokens_data.get("error"):
        await update.message.reply_text(
            f"❌ *Error fetching tokens*\n\n{tokens_data['error']}", 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    if not tokens_data["tokens"]:
        await update.message.reply_text(
            "💫 *No tokens found*\n\nThis wallet doesn't appear to hold any tokens or objects.", 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Format token list
    total_value_usd = tokens_data.get("total_value_usd", 0)
    response = f"🪙 *TOKEN HOLDINGS* 🪙\n"
    response += f"━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"*Address:* `{wallet_address[:6]}...{wallet_address[-4:]}`\n"
    response += f"💵 *Total Value:* ${total_value_usd:.2f} USD\n\n"
    
    # Process and sort tokens
    coin_tokens = []
    nft_tokens = []
    
    for token_type, token_info in tokens_data["tokens"].items():
        token_name = token_info["name"]
        token_count = token_info["count"]
        token_balance = token_info.get("balance_formatted")
        token_value = token_info.get("value_usd", 0)
        
        if token_balance is not None:  # This is a coin
            if token_type == "0x2::sui::SUI":
                balance_str = f"{token_balance:.6f}"
                value_str = f"${token_value:.2f}"
                coin_tokens.append(f"🔸 *{token_name}*: {balance_str} ({value_str})")
            else:
                balance_str = f"{token_balance}"
                value_str = f"${token_value:.2f}" if token_value > 0 else "N/A"
                coin_tokens.append(f"🔹 *{token_name}*: {balance_str} ({value_str})")
        else:  # This is an NFT or other object
            nft_tokens.append(f"🔶 *{token_name}*: {token_count} objects")
    
    # Add coins first
    if coin_tokens:
        response += "*Coins:*\n" + "\n".join(coin_tokens) + "\n\n"
    
    # Then add NFTs/other objects
    if nft_tokens:
        response += "*Other Objects:*\n" + "\n".join(nft_tokens)
    
    response += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"Use `/check {wallet_address}` for wallet overview"
    
    # If the message is too long, split it
    if len(response) > 4000:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                await update.message.reply_text(
                    chunk, 
                    parse_mode='Markdown', 
                    reply_markup=reply_markup if i == 0 else None
                )
            else:
                await update.message.reply_text(
                    f"*Continued ({i+1}/{len(chunks)})*\n\n{chunk}", 
                    parse_mode='Markdown'
                )
    else:
        await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reply_markup)

# Function to analyze Sui token contracts
async def get_token_contract_info(token_address):
    try:
        # Get token object data
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sui_getObject",
            "params": [token_address, {
                "showContent": True,
                "showDisplay": True,
                "showOwner": True,
                "showType": True,
                "showPreviousTransaction": True
            }]
        }
        
        response = requests.post(SUI_RPC_URL, json=payload)
        data = response.json()
        
        if "error" in data:
            return {"error": f"Error: {data['error']['message']}"}
        
        if "result" not in data or "data" not in data["result"]:
            return {"error": "Invalid token contract address or object not found"}
        
        object_data = data["result"]["data"]
        token_info = {
            "address": token_address,
            "type": object_data.get("type", "Unknown"),
            "owner": object_data.get("owner", "Unknown"),
            "package": None,
            "module": None,
            "name": None,
            "symbol": None,
            "decimals": None,
            "supply": None,
            "description": None,
            "creation_tx": object_data.get("previousTransaction", None),
            "deployer": None,
            "first_buyers": [],
            "error": None
        }
        
        # Extract token name and symbol if available
        if "display" in object_data and "data" in object_data["display"]:
            display_data = object_data["display"]["data"]
            token_info["name"] = display_data.get("name", "Unknown")
            token_info["description"] = display_data.get("description", "Unknown")
            token_info["symbol"] = display_data.get("symbol", token_info["name"])
        
        # Parse type to get package and module info
        if token_info["type"] and "::" in token_info["type"]:
            type_parts = token_info["type"].split("::")
            if len(type_parts) >= 2:
                token_info["package"] = type_parts[0]
                token_info["module"] = type_parts[1]
        
        # Get additional token details if it's a coin
        if "coin" in token_info["type"].lower() or "token" in token_info["type"].lower():
            # Try to get total supply
            try:
                # Get coin metadata if available
                metadata_payload = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "suix_getCoinMetadata",
                    "params": [token_address]
                }
                
                metadata_response = requests.post(SUI_RPC_URL, json=metadata_payload)
                metadata_data = metadata_response.json()
                
                if "result" in metadata_data and metadata_data["result"]:
                    metadata = metadata_data["result"]
                    token_info["decimals"] = metadata.get("decimals", 9)
                    token_info["symbol"] = metadata.get("symbol", token_info["symbol"])
                    token_info["name"] = metadata.get("name", token_info["name"])
                    
                    # Get total supply if available
                    if "supply" in metadata:
                        raw_supply = int(metadata["supply"])
                        token_info["supply"] = raw_supply / (10 ** token_info["decimals"])
            except Exception as e:
                logger.error(f"Error fetching token metadata: {str(e)}")
        
        # Get token events
        try:
            events_payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "suix_queryEvents",
                "params": [
                    {"MoveEventModule": token_info["module"] if token_info["module"] else ""},
                    {"limit": 10, "descendingOrder": True},
                    None
                ]
            }
            
            events_response = requests.post(SUI_RPC_URL, json=events_payload)
            events_data = events_response.json()
            
            if "result" in events_data and "data" in events_data["result"]:
                token_info["recent_events"] = len(events_data["result"]["data"])
            else:
                token_info["recent_events"] = 0
        except Exception as e:
            logger.error(f"Error fetching token events: {str(e)}")
            token_info["recent_events"] = 0
        
        # Get creation transaction and deployer info
        if token_info["creation_tx"]:
            try:
                # Fetch the creation transaction to get the deployer
                creation_tx_payload = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "sui_getTransactionBlock",
                    "params": [
                        token_info["creation_tx"],
                        {
                            "showEffects": True,
                            "showInput": True,
                            "showEvents": True
                        }
                    ]
                }
                
                creation_tx_response = requests.post(SUI_RPC_URL, json=creation_tx_payload)
                creation_tx_data = creation_tx_response.json()
                
                if "result" in creation_tx_data:
                    tx_result = creation_tx_data["result"]
                    # Get deployer (sender of creation transaction)
                    if "sender" in tx_result:
                        token_info["deployer"] = tx_result["sender"]
                    
                    # Additional deploy info
                    if "timestampMs" in tx_result:
                        deploy_time_ms = int(tx_result["timestampMs"])
                        # Convert to human-readable date
                        from datetime import datetime
                        deploy_date = datetime.fromtimestamp(deploy_time_ms / 1000)
                        token_info["deploy_date"] = deploy_date.strftime("%Y-%m-%d")
                        token_info["deploy_time"] = deploy_date.strftime("%H:%M:%S UTC")
            except Exception as e:
                logger.error(f"Error fetching creation transaction: {str(e)}")
        
        # Estimate holder count and activity
        # Note: This is an approximation as the RPC API doesn't directly provide this
        try:
            # We'll use a proxy to estimate - checking how many distinct addresses 
            # have interacted with the token recently
            interactions_payload = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "suix_queryTransactionBlocks",
                "params": [
                    {"InputObject": token_address},
                    {"limit": 100, "descendingOrder": True},
                    None
                ]
            }
            
            interactions_response = requests.post(SUI_RPC_URL, json=interactions_payload)
            interactions_data = interactions_response.json()
            
            unique_addresses = set()
            first_buyers = []
            tx_count = 0
            
            if "result" in interactions_data and "data" in interactions_data["result"]:
                tx_list = interactions_data["result"]["data"]
                tx_count = len(tx_list)
                
                for tx in tx_list:
                    if "sender" in tx:
                        sender = tx["sender"]
                        unique_addresses.add(sender)
                        
                        # Keep track of first few buyers/interactors (excluding deployer)
                        if sender != token_info.get("deployer") and len(first_buyers) < 3:
                            if sender not in first_buyers:
                                first_buyers.append(sender)
                
                # Store first buyers
                token_info["first_buyers"] = first_buyers
            
            token_info["estimated_holders"] = len(unique_addresses)
            token_info["transaction_count"] = tx_count
            
            # Determine activity level
            if tx_count == 0:
                token_info["activity_level"] = "Inactive"
            elif tx_count < 10:
                token_info["activity_level"] = "Low"
            elif tx_count < 50:
                token_info["activity_level"] = "Moderate"
            else:
                token_info["activity_level"] = "High"
                
        except Exception as e:
            logger.error(f"Error estimating token holders: {str(e)}")
            token_info["estimated_holders"] = "Unknown"
            token_info["transaction_count"] = 0
            token_info["activity_level"] = "Unknown"
        
        return token_info
    except Exception as e:
        logger.error(f"Error analyzing token contract: {str(e)}")
        return {"error": f"Error analyzing token contract: {str(e)}"}

# Command handler for token contract analysis
async def token_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get token address from command arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "🔍 *Please provide a Sui token contract address*\n\n"
            "Example: `/token_info 0x2::sui::SUI` or `/token_info 0x123...`\n\n"
            "Type the token address or ID after the command to view details.",
            parse_mode='Markdown'
        )
        return
    
    token_address = context.args[0]
    
    # Validate address format
    if not token_address.startswith("0x") and "::" not in token_address:
        await update.message.reply_text(
            "❌ *Invalid token format*\n\n"
            "Please use a valid Sui object ID starting with '0x' or a fully qualified type like '0x2::sui::SUI'.",
            parse_mode='Markdown'
        )
        return
    
    # Show a loading message
    loading_message = await update.message.reply_text(f"🔍 Analyzing token: {token_address}...")
    
    # Get token information
    token_info = await get_token_contract_info(token_address)
    
    if token_info.get("error"):
        await update.message.reply_text(
            f"❌ *Error analyzing token*\n\n{token_info['error']}", 
            parse_mode='Markdown'
        )
        return
    
    # Build explorer links
    suiscan_link = f"{SUISCAN_URL}object/{token_address}"
    suivision_link = f"{SUIVISION_URL}object/{token_address}"
    
    # Create keyboard with explorer links
    keyboard = [
        [
            InlineKeyboardButton("🔍 View on SuiScan", url=suiscan_link),
            InlineKeyboardButton("📊 View on SuiVision", url=suivision_link)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format response
    response = f"🪙 *TOKEN ANALYSIS* 🪙\n"
    response += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    response += f"*Token:* {token_info.get('name', 'Unknown')}"
    if token_info.get('symbol') and token_info['symbol'] != token_info.get('name', ''):
        response += f" ({token_info['symbol']})\n"
    else:
        response += "\n"
    
    response += f"*Address:* `{token_address[:10]}...{token_address[-4:] if len(token_address) > 14 else token_address[-4:]}`\n"
    
    if token_info.get('type'):
        response += f"*Type:* `{token_info['type']}`\n"
    
    if token_info.get('description') and token_info['description'] != 'Unknown':
        response += f"*Description:* {token_info['description']}\n"
    
    response += "\n"
    
    # Add deployment information
    if token_info.get('deployer'):
        response += f"👨‍💻 *Deployer:* `{token_info['deployer'][:8]}...{token_info['deployer'][-4:]}`\n"
    
    if token_info.get('deploy_date'):
        response += f"📅 *Deployed on:* {token_info['deploy_date']}\n"
    
    if token_info.get('deploy_time'):
        response += f"🕒 *Deploy time:* {token_info['deploy_time']}\n"
    
    # Add first buyers/interactors if available
    if token_info.get('first_buyers') and len(token_info['first_buyers']) > 0:
        response += f"\n👥 *First Interactors:*\n"
        for i, buyer in enumerate(token_info['first_buyers']):
            response += f"   {i+1}. `{buyer[:8]}...{buyer[-4:]}`\n"
    
    response += "\n"
    
    # Add supply information if available
    if token_info.get('supply') is not None:
        response += f"💰 *Total Supply:* {token_info['supply']:,.2f}"
        if token_info.get('symbol'):
            response += f" {token_info['symbol']}\n"
        else:
            response += "\n"
    
    if token_info.get('decimals') is not None:
        response += f"🔢 *Decimals:* {token_info['decimals']}\n"
    
    response += "\n"
    
    # Add activity information
    if token_info.get('activity_level'):
        emoji_map = {
            "Inactive": "⚪",
            "Low": "🟠",
            "Moderate": "🟢",
            "High": "🟢🟢"
        }
        activity_emoji = emoji_map.get(token_info['activity_level'], "⚪")
        response += f"🔄 *Activity Level:* {activity_emoji} {token_info['activity_level']}\n"
    
    if token_info.get('transaction_count') is not None:
        response += f"📊 *Recent Transactions:* {token_info['transaction_count']}\n"
    
    if token_info.get('estimated_holders') is not None and token_info['estimated_holders'] != 'Unknown':
        response += f"👥 *Est. Holders:* {token_info['estimated_holders']}\n"
    
    if token_info.get('recent_events') is not None:
        response += f"📡 *Recent Events:* {token_info['recent_events']}\n"
    
    response += "\n"
    
    # Add ownership information
    if token_info.get('owner') and token_info['owner'] != 'Unknown':
        owner_type = "Unknown"
        owner_address = "Unknown"
        
        if isinstance(token_info['owner'], dict):
            if "AddressOwner" in token_info['owner']:
                owner_type = "Address"
                owner_address = token_info['owner']["AddressOwner"]
            elif "ObjectOwner" in token_info['owner']:
                owner_type = "Object"
                owner_address = token_info['owner']["ObjectOwner"]
            elif "Shared" in token_info['owner']:
                owner_type = "Shared"
                owner_address = "Multiple Owners"
        
        response += f"👤 *Ownership:* {owner_type}\n"
        if owner_address != "Multiple Owners" and owner_address != "Unknown":
            response += f"📝 *Owner:* `{owner_address[:10]}...{owner_address[-4:]}`\n"
    
    response += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"Use `/check <address>` to analyze wallet stats"
    
    # Send final response
    await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reply_markup)


# Function to analyze early trades and liquidity of a token
async def get_token_trading_info(token_address):
    try:
        # This function will attempt to find early trading data for a token
        # First, we'll look for events related to token creation or liquidity addition
        
        # Get token type from the object first
        token_info = await get_token_contract_info(token_address)
        if token_info.get("error"):
            return {"error": token_info["error"]}
        
        token_type = token_info.get("type", "")
        if not token_type:
            return {"error": "Couldn't determine token type"}
        
        # Extract module and package information
        package = token_info.get("package")
        module = token_info.get("module")
        
        if not package or not module:
            return {"error": "Couldn't extract package or module information"}
        
        # Look for liquidity pool events related to this token
        # This is a simplified approach and might need to be adapted based on the DEX being used
        liquidity_events_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_queryEvents",
            "params": [
                {"MoveEventType": f"{package}::{module}::LiquidityAdded"},
                {"limit": 20, "descendingOrder": True},
                None
            ]
        }
        
        liq_response = requests.post(SUI_RPC_URL, json=liquidity_events_payload)
        liq_data = liq_response.json()
        
        # Also try looking for transfer events
        transfer_events_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "suix_queryEvents",
            "params": [
                {"MoveEventType": f"{package}::{module}::TransferEvent"},
                {"limit": 20, "descendingOrder": True},
                None
            ]
        }
        
        transfer_response = requests.post(SUI_RPC_URL, json=transfer_events_payload)
        transfer_data = transfer_response.json()
        
        # We'll try another common event type
        mint_events_payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "suix_queryEvents",
            "params": [
                {"MoveEventType": f"{package}::{module}::MintEvent"},
                {"limit": 20, "descendingOrder": True},
                None
            ]
        }
        
        mint_response = requests.post(SUI_RPC_URL, json=mint_events_payload)
        mint_data = mint_response.json()
        
        # Initialize results
        trading_info = {
            "liquidity_events": [],
            "transfer_events": [],
            "mint_events": [],
            "first_liquidity_provider": None,
            "first_liquidity_amount": None,
            "first_liquidity_time": None,
            "early_minters": [],
            "early_traders": []
        }
        
        # Parse liquidity events
        if "result" in liq_data and "data" in liq_data["result"] and liq_data["result"]["data"]:
            events = liq_data["result"]["data"]
            trading_info["liquidity_events"] = len(events)
            
            # Try to extract first liquidity provider
            if events and len(events) > 0:
                first_event = events[-1]  # The earliest event should be last in the list
                
                # Extract timestamp if available
                if "timestampMs" in first_event:
                    timestamp_ms = int(first_event["timestampMs"])
                    from datetime import datetime
                    event_date = datetime.fromtimestamp(timestamp_ms / 1000)
                    trading_info["first_liquidity_time"] = event_date.strftime("%Y-%m-%d %H:%M:%S UTC")
                
                # Try to extract sender (liquidity provider)
                if "sender" in first_event:
                    trading_info["first_liquidity_provider"] = first_event["sender"]
                
                # Try to extract amount (this is highly DEX-specific)
                if "parsedJson" in first_event and first_event["parsedJson"]:
                    parsed = first_event["parsedJson"]
                    if "amount" in parsed:
                        trading_info["first_liquidity_amount"] = parsed["amount"]
        
        # Parse transfer events
        if "result" in transfer_data and "data" in transfer_data["result"] and transfer_data["result"]["data"]:
            events = transfer_data["result"]["data"]
            trading_info["transfer_events"] = len(events)
            
            # Extract early traders
            early_traders = set()
            for event in events[:min(5, len(events))]:
                if "sender" in event and event["sender"] not in early_traders:
                    early_traders.add(event["sender"])
            
            trading_info["early_traders"] = list(early_traders)
        
        # Parse mint events
        if "result" in mint_data and "data" in mint_data["result"] and mint_data["result"]["data"]:
            events = mint_data["result"]["data"]
            trading_info["mint_events"] = len(events)
            
            # Extract early minters
            early_minters = set()
            for event in events[:min(5, len(events))]:
                if "sender" in event and event["sender"] not in early_minters:
                    early_minters.add(event["sender"])
            
            trading_info["early_minters"] = list(early_minters)
        
        return trading_info
    except Exception as e:
        logger.error(f"Error analyzing token trading: {str(e)}")
        return {"error": f"Error analyzing token trading: {str(e)}"}

# Function to check if addresses are related (share transactions)
async def check_related_addresses(address_list):
    if not address_list or len(address_list) < 2:
        return {"related": False, "reason": "Not enough addresses to compare"}
    
    try:
        related_info = {
            "related": False,
            "common_transactions": [],
            "transaction_patterns": False,
            "reason": "No relationship detected"
        }
        
        # Check for common transactions between addresses
        # This is a simplified approach - production systems would use more sophisticated methods
        
        # Get recent transactions for each address
        address_transactions = {}
        
        for address in address_list:
            # Get transactions sent by this address
            tx_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "suix_queryTransactionBlocks",
                "params": [
                    {"FromAddress": address},
                    {"limit": 20, "descendingOrder": True},
                    None
                ]
            }
            
            tx_response = requests.post(SUI_RPC_URL, json=tx_payload)
            tx_data = tx_response.json()
            
            if "result" in tx_data and "data" in tx_data["result"]:
                address_transactions[address] = set(tx["digest"] for tx in tx_data["result"]["data"])
            else:
                address_transactions[address] = set()
        
        # Check for common transactions
        common_txs = set()
        addresses = list(address_transactions.keys())
        
        for i in range(len(addresses)):
            for j in range(i+1, len(addresses)):
                addr1 = addresses[i]
                addr2 = addresses[j]
                
                # Find intersection of transaction sets
                intersection = address_transactions[addr1].intersection(address_transactions[addr2])
                common_txs.update(intersection)
        
        # If we found common transactions, they might be related
        if common_txs:
            related_info["related"] = True
            related_info["common_transactions"] = list(common_txs)
            related_info["reason"] = f"Found {len(common_txs)} common transactions"
        
        # Add more sophisticated pattern detection here in a production system
        
        return related_info
    except Exception as e:
        logger.error(f"Error checking related addresses: {str(e)}")
        return {"error": f"Error checking related addresses: {str(e)}"}

# Enhanced token info command that includes trading analysis and relationship checks
async def enhanced_token_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # This is an extended version of token_info_command with additional analysis
    # For production, you might want to merge this with your main token_info_command
    
    # Get token address from command arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "🔍 *Please provide a Sui token contract address*\n\n"
            "Example: `/token_info 0x2::sui::SUI` or `/token_info 0x123...`\n\n"
            "Type the token address or ID after the command to view details.",
            parse_mode='Markdown'
        )
        return
    
    token_address = context.args[0]
    
    # Validate address format
    if not token_address.startswith("0x") and "::" not in token_address:
        await update.message.reply_text(
            "❌ *Invalid token format*\n\n"
            "Please use a valid Sui object ID starting with '0x' or a fully qualified type like '0x2::sui::SUI'.",
            parse_mode='Markdown'
        )
        return
    
    # Show a loading message
    loading_message = await update.message.reply_text(f"🔍 Analyzing token: {token_address}...")
    
    # Get basic token information
    token_info = await get_token_contract_info(token_address)
    
    if token_info.get("error"):
        await update.message.reply_text(
            f"❌ *Error analyzing token*\n\n{token_info['error']}", 
            parse_mode='Markdown'
        )
        return
    
    # Get additional trading information
    trading_info = await get_token_trading_info(token_address)
    
    # Check for relationships between deployer and first buyers
    addresses_to_check = [addr for addr in [token_info.get("deployer")] + token_info.get("first_buyers", []) if addr]
    relationship_info = await check_related_addresses(addresses_to_check) if len(addresses_to_check) >= 2 else None
    
    # Build explorer links
    suiscan_link = f"{SUISCAN_URL}object/{token_address}"
    suivision_link = f"{SUIVISION_URL}object/{token_address}"
    
    # Create keyboard with explorer links
    keyboard = [
        [
            InlineKeyboardButton("🔍 View on SuiScan", url=suiscan_link),
            InlineKeyboardButton("📊 View on SuiVision", url=suivision_link)
        ]
    ]
    
    # Add link to check deployer if available
    if token_info.get("deployer"):
        keyboard.append([
            InlineKeyboardButton("👨‍💻 Check Deployer", url=f"{SUISCAN_URL}account/{token_info['deployer']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format basic response (same as token_info_command)
    response = f"🪙 *TOKEN ANALYSIS* 🪙\n"
    response += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    response += f"*Token:* {token_info.get('name', 'Unknown')}"
    if token_info.get('symbol') and token_info['symbol'] != token_info.get('name', ''):
        response += f" ({token_info['symbol']})\n"
    else:
        response += "\n"
    
    response += f"*Address:* `{token_address[:10]}...{token_address[-4:] if len(token_address) > 14 else token_address[-4:]}`\n"
    
    if token_info.get('type'):
        response += f"*Type:* `{token_info['type']}`\n"
    
    if token_info.get('description') and token_info['description'] != 'Unknown':
        response += f"*Description:* {token_info['description']}\n"
    
    response += "\n"
    
    # Add deployment information
    if token_info.get('deployer'):
        response += f"👨‍💻 *Deployer:* `{token_info['deployer'][:8]}...{token_info['deployer'][-4:]}`\n"
    
    if token_info.get('deploy_date'):
        response += f"📅 *Deployed on:* {token_info['deploy_date']}\n"
    
    if token_info.get('deploy_time'):
        response += f"🕒 *Deploy time:* {token_info['deploy_time']}\n"
    
    # Add first buyers/interactors if available
    if token_info.get('first_buyers') and len(token_info['first_buyers']) > 0:
        response += f"\n👥 *First Interactors:*\n"
        for i, buyer in enumerate(token_info['first_buyers']):
            response += f"   {i+1}. `{buyer[:8]}...{buyer[-4:]}`\n"
    
    # Add relationship analysis if available
    if relationship_info and not relationship_info.get("error"):
        if relationship_info.get("related"):
            response += f"\n⚠️ *Potential Related Addresses:* Yes\n"
            response += f"   {relationship_info.get('reason', 'Common transaction patterns detected')}\n"
        else:
            response += f"\n✅ *Related Addresses:* No evidence found\n"
    
    # Add trading information if available
    if trading_info and not trading_info.get("error"):
        response += f"\n💱 *Trading Analysis:*\n"
        
        if trading_info.get("first_liquidity_provider"):
            response += f"   First LP: `{trading_info['first_liquidity_provider'][:8]}...{trading_info['first_liquidity_provider'][-4:]}`\n"
        
        if trading_info.get("first_liquidity_time"):
            response += f"   First Liquidity: {trading_info['first_liquidity_time']}\n"
        
        if trading_info.get("liquidity_events"):
            response += f"   Liquidity Events: {trading_info['liquidity_events']}\n"
        
        if trading_info.get("transfer_events"):
            response += f"   Transfer Events: {trading_info['transfer_events']}\n"
        
        if trading_info.get("mint_events"):
            response += f"   Mint Events: {trading_info['mint_events']}\n"
    
    response += "\n"
    
    # Add supply information if available
    if token_info.get('supply') is not None:
        response += f"💰 *Total Supply:* {token_info['supply']:,.2f}"
        if token_info.get('symbol'):
            response += f" {token_info['symbol']}\n"
        else:
            response += "\n"
    
    if token_info.get('decimals') is not None:
        response += f"🔢 *Decimals:* {token_info['decimals']}\n"
    
    response += "\n"
    
    # Add activity information
    if token_info.get('activity_level'):
        emoji_map = {
            "Inactive": "⚪",
            "Low": "🟠",
            "Moderate": "🟢",
            "High": "🟢🟢"
        }
        activity_emoji = emoji_map.get(token_info['activity_level'], "⚪")
        response += f"🔄 *Activity Level:* {activity_emoji} {token_info['activity_level']}\n"
    
    if token_info.get('transaction_count') is not None:
        response += f"📊 *Recent Transactions:* {token_info['transaction_count']}\n"
    
    if token_info.get('estimated_holders') is not None and token_info['estimated_holders'] != 'Unknown':
        response += f"👥 *Est. Holders:* {token_info['estimated_holders']}\n"
    
    if token_info.get('recent_events') is not None:
        response += f"📡 *Recent Events:* {token_info['recent_events']}\n"
    
    response += "\n"
    
    # Add ownership information
    if token_info.get('owner') and token_info['owner'] != 'Unknown':
        owner_type = "Unknown"
        owner_address = "Unknown"
        
        if isinstance(token_info['owner'], dict):
            if "AddressOwner" in token_info['owner']:
                owner_type = "Address"
                owner_address = token_info['owner']["AddressOwner"]
            elif "ObjectOwner" in token_info['owner']:
                owner_type = "Object"
                owner_address = token_info['owner']["ObjectOwner"]
            elif "Shared" in token_info['owner']:
                owner_type = "Shared"
                owner_address = "Multiple Owners"
        
        response += f"👤 *Ownership:* {owner_type}\n"
        if owner_address != "Multiple Owners" and owner_address != "Unknown":
            response += f"📝 *Owner:* `{owner_address[:10]}...{owner_address[-4:]}`\n"
    
    # Add risk assessment section
    response += f"\n🔒 *Risk Assessment:*\n"
    
    # Calculate risk factors
    risk_factors = []
    risk_level = "Low"
    
    # Check for recently deployed tokens (potential risk)
    if token_info.get('deploy_date'):
        from datetime import datetime, timedelta
        deploy_date = datetime.strptime(token_info['deploy_date'], "%Y-%m-%d")
        days_since_deploy = (datetime.now() - deploy_date).days
        
        if days_since_deploy < 3:
            risk_factors.append("Very recent token (less than 3 days old)")
            risk_level = "High"
        elif days_since_deploy < 7:
            risk_factors.append("New token (less than 7 days old)")
            risk_level = "Medium"
    
    # Check for related addresses between deployer and first interactors
    if relationship_info and relationship_info.get("related"):
        risk_factors.append("Related addresses detected between deployer and early interactors")
        if risk_level != "High":
            risk_level = "Medium"
    
    # Check for low transaction count
    if token_info.get('transaction_count') is not None and token_info['transaction_count'] < 10:
        risk_factors.append("Low transaction volume")
        if risk_level != "High":
            risk_level = "Medium"
    
    # Display risk assessment
    risk_emoji = {
        "Low": "🟢",
        "Medium": "🟠",
        "High": "🔴"
    }
    
    response += f"   *Level:* {risk_emoji.get(risk_level, '⚪')} {risk_level}\n"
    
    if risk_factors:
        response += "   *Factors:*\n"
        for factor in risk_factors:
            response += f"     - {factor}\n"
    else:
        response += "   No significant risk factors detected\n"
    
    response += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"Use `/check <address>` to analyze wallet stats"
    
    # Delete the loading message and send the final response
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=loading_message.message_id)
    await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reply_markup)
    

# main fuction

def main() -> None:
    # Get the token from environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No token provided. Set the TELEGRAM_BOT_TOKEN environment variable.")
        return
    
    # Create the Application
    application = Application.builder().token(token).build()
    
   # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_wallet))
    application.add_handler(CommandHandler("token", token_command))
    application.add_handler(CommandHandler("token_info", token_info_command))
    application.add_handler(CommandHandler("enhanced_token_info", enhanced_token_info_command))  # Add this new command
    
    # Run the bot
    application.run_polling()
    
if __name__ == "__main__":
    main()