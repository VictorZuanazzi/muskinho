"""
Twilio Connection Testing Script
Tests your Twilio credentials and WhatsApp integration
"""

import os
import sys
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# Load environment variables
load_dotenv()

# Get credentials from environment
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def print_success(text):
    """Print success message"""
    print(f"✓ {text}")

def print_error(text):
    """Print error message"""
    print(f"✗ {text}")

def print_warning(text):
    """Print warning message"""
    print(f"⚠ {text}")

def print_info(text):
    """Print info message"""
    print(f"ℹ {text}")

def test_credentials_exist():
    """Test 1: Check if credentials are set"""
    print_header("TEST 1: Checking Credentials")
    
    if not ACCOUNT_SID:
        print_error("TWILIO_ACCOUNT_SID is not set in .env file")
        return False
    else:
        print_success(f"ACCOUNT_SID found: {ACCOUNT_SID[:10]}...")
    
    if not AUTH_TOKEN:
        print_error("TWILIO_AUTH_TOKEN is not set in .env file")
        return False
    else:
        print_success(f"AUTH_TOKEN found: {AUTH_TOKEN[:10]}...")
    
    if not TWILIO_WHATSAPP_NUMBER:
        print_error("TWILIO_WHATSAPP_NUMBER is not set in .env file")
        return False
    else:
        print_success(f"WHATSAPP_NUMBER found: {TWILIO_WHATSAPP_NUMBER}")
    
    return True

def test_twilio_client_creation():
    """Test 2: Try to create Twilio client"""
    print_header("TEST 2: Creating Twilio Client")
    
    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        print_success("Twilio client created successfully")
        return client
    except TwilioRestException as e:
        print_error(f"Failed to create Twilio client: {e}")
        return None
    except Exception as e:
        print_error(f"Unexpected error creating client: {e}")
        return None

def test_account_info(client):
    """Test 3: Fetch account information"""
    print_header("TEST 3: Fetching Account Information")
    
    try:
        account = client.api.accounts(ACCOUNT_SID).fetch()
        print_success("Successfully fetched account information")
        print_info(f"Account Status: {account.status}")
        print_info(f"Account Type: {account.type}")
        print_info(f"Account Name: {account.friendly_name}")
        return True
    except TwilioRestException as e:
        print_error(f"Failed to fetch account info: {e}")
        print_warning("This might indicate invalid credentials")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False

def test_phone_numbers(client):
    """Test 4: List available phone numbers"""
    print_header("TEST 4: Listing Phone Numbers")
    
    try:
        phone_numbers = client.incoming_phone_numbers.stream(limit=10)
        phone_list = list(phone_numbers)
        
        if phone_list:
            print_success(f"Found {len(phone_list)} phone number(s)")
            for phone in phone_list:
                print_info(f"  • {phone.phone_number} - {phone.friendly_name}")
        else:
            print_warning("No phone numbers found in your account")
        
        return True
    except TwilioRestException as e:
        print_error(f"Failed to list phone numbers: {e}")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False

def test_whatsapp_sandbox(client):
    """Test 5: Check WhatsApp sandbox status"""
    print_header("TEST 5: Checking WhatsApp Sandbox")
    
    try:
        # Try to get WhatsApp sandbox info
        services = client.messaging.v1.services.list(limit=10)
        whatsapp_services = [s for s in services if 'whatsapp' in s.friendly_name.lower()]
        
        if whatsapp_services:
            print_success("WhatsApp service found")
            for service in whatsapp_services:
                print_info(f"  • {service.friendly_name}")
        else:
            print_warning("No WhatsApp services found")
            print_info("You may need to set up WhatsApp in your Twilio console")
        
        return True
    except Exception as e:
        print_warning(f"Could not check WhatsApp services: {e}")
        print_info("This is OK - you can still use WhatsApp")
        return True

def test_send_test_message(client):
    """Test 6: Attempt to send a test message"""
    print_header("TEST 6: Sending Test Message")
    
    # Ask user for phone number
    # print_info("To test sending a message, we need a phone number to send to.")
    test_phone = os.getenv("DESTINATION_WHATSAPP_NUMBER")
    # test_phone = input("Enter a phone number to test (with country code, e.g., +1234567890): ").strip()
    
    if not test_phone:
        print_warning("No phone number provided, skipping test message")
        return None
    
    try:
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body="🧪 Test message from Twilio WhatsApp Bot - Connection successful!",
            to=test_phone
        )
        
        print_success(f"Test message sent successfully!")
        print_info(f"Message SID: {message.sid}")
        print_info(f"Status: {message.status}")
        return True
    except TwilioRestException as e:
        print_error(f"Failed to send message: {e}")
        print_warning("Possible reasons:")
        print_warning("  • Phone number not in WhatsApp sandbox")
        print_warning("  • Invalid phone number format")
        print_warning("  • WhatsApp not properly configured")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False

def test_webhook_configuration():
    """Test 7: Webhook configuration guide"""
    print_header("TEST 7: Webhook Configuration")
    
    print_info("To complete the setup, you need to configure the webhook in Twilio:")
    print_info("")
    print_info("1. Go to: https://www.twilio.com/console/messaging/whatsapp/learn")
    print_info("2. Find 'When a message comes in' section")
    print_info("3. Set the webhook URL to your deployed app:")
    print_info("   https://your-app-domain.com/webhook")
    print_info("")
    print_info("4. Make sure it's set to POST method")
    print_info("5. Save the configuration")
    print_info("")
    print_info("For local testing, you can use ngrok to expose your local server:")
    print_info("   ngrok http 5000")
    print_info("   Then use: https://your-ngrok-url.ngrok.io/webhook")

def run_all_tests():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  TWILIO CONNECTION TEST SUITE".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")
    
    results = {}
    
    # Test 1: Credentials
    results["Credentials"] = test_credentials_exist()
    if not results["Credentials"]:
        print_error("\nCannot proceed without credentials. Please set up your .env file.")
        return results
    
    # Test 2: Client creation
    client = test_twilio_client_creation()
    results["Client Creation"] = client is not None
    if not client:
        print_error("\nCannot proceed without valid client. Check your credentials.")
        return results
    
    # Test 3: Account info
    results["Account Info"] = test_account_info(client)
    
    # Test 4: Phone numbers
    results["Phone Numbers"] = test_phone_numbers(client)
    
    # Test 5: WhatsApp sandbox
    results["WhatsApp Sandbox"] = test_whatsapp_sandbox(client)
    
    # Test 6: Send test message
    results["Send Message"] = test_send_test_message(client)
    
    # Test 7: Webhook configuration
    test_webhook_configuration()
    
    # Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    
    for test_name, result in results.items():
        if result is True:
            print_success(f"{test_name}")
        elif result is False:
            print_error(f"{test_name}")
        else:
            print_warning(f"{test_name} (skipped)")
    
    print("\n" + "-" * 60)
    print(f"Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print("-" * 60)
    
    if failed == 0:
        print_success("\n✓ All tests passed! Your Twilio connection is ready.")
    else:
        print_error(f"\n✗ {failed} test(s) failed. Please review the errors above.")
    
    return results

if __name__ == "__main__":
    run_all_tests()
