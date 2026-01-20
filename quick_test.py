"""
Quick Twilio Connection Test
Simple script to verify basic Twilio connectivity
"""

import os
from dotenv import load_dotenv
from twilio.rest import Client

# Load environment variables
load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

print("🔍 Quick Twilio Connection Test\n")

# Check if credentials exist
if not ACCOUNT_SID or not AUTH_TOKEN:
    print("❌ Error: Credentials not found in .env file")
    print("   Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
    exit(1)

print("✓ Credentials found")
print(f"  Account SID: {ACCOUNT_SID[:10]}...")
print(f"  Auth Token: {AUTH_TOKEN[:10]}...\n")

# Try to create client
try:
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    print("✓ Twilio client created successfully")
except Exception as e:
    print(f"❌ Failed to create client: {e}")
    exit(1)

# Try to fetch account
try:
    account = client.api.accounts(ACCOUNT_SID).fetch()
    print(f"✓ Account verified: {account.friendly_name}")
    print(f"  Status: {account.status}")
except Exception as e:
    print(f"❌ Failed to verify account: {e}")
    exit(1)

print("\n✅ Connection successful! Your Twilio credentials are valid.")
