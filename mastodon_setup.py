#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mastodon Account Setup and Token Generation
Interactive script to create Mastodon app and get access token

Created: 2026-02-26
"""

from mastodon import Mastodon
import os

print("=" * 70)
print(" MASTODON SETUP - Generate Access Token")
print("=" * 70)
print()

# Step 1: Choose instance
print("STEP 1: Choose a Mastodon instance")
print("-" * 70)
print("Popular instances:")
print("  • mastodon.social (largest, general)")
print("  • fosstodon.org (tech/FOSS focused)")
print("  • mastodon.online (general)")
print("  • mstdn.social (general)")
print()
print("You can use any Mastodon instance.")
print("More at: https://joinmastodon.org/servers")
print()

instance = input("Enter instance URL [mastodon.social]: ").strip()
if not instance:
    instance = "mastodon.social"

if not instance.startswith("http"):
    instance = f"https://{instance}"

print(f"\n✅ Using: {instance}")

# Step 2: Register app
print("\n" + "=" * 70)
print("STEP 2: Register application")
print("-" * 70)

app_name = input("Enter app name [pyTweeter News Collector]: ").strip()
if not app_name:
    app_name = "pyTweeter News Collector"

print(f"\nRegistering '{app_name}' on {instance}...")

try:
    client_id, client_secret = Mastodon.create_app(
        app_name,
        api_base_url=instance,
        scopes=['read', 'write'],
        website='https://github.com/yourusername/pyTweeter'  # Optional
    )
    
    print("✅ App registered successfully!")
    print(f"   Client ID: {client_id[:20]}...")
    print(f"   Client Secret: {client_secret[:20]}...")
    
except Exception as e:
    print(f"❌ Failed to register app: {e}")
    print("\nTry manually:")
    print(f"1. Go to: {instance}/settings/applications/new")
    print("2. Create app with 'read' and 'write' scopes")
    print("3. Copy the access token")
    exit(1)

# Step 3: Login
print("\n" + "=" * 70)
print("STEP 3: Login to your account")
print("-" * 70)
print("Enter your Mastodon credentials:")
print()

email = input("Email: ").strip()
password = input("Password: ").strip()

if not email or not password:
    print("\n❌ Email and password are required")
    exit(1)

try:
    mastodon = Mastodon(
        client_id=client_id,
        client_secret=client_secret,
        api_base_url=instance
    )
    
    access_token = mastodon.log_in(
        email,
        password,
        scopes=['read', 'write']
    )
    
    print("\n✅ Login successful!")
    
    # Verify
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=instance
    )
    account = mastodon.account_verify_credentials()
    
    print(f"✅ Connected as: @{account['username']}")
    print(f"   Display name: {account['display_name']}")
    print(f"   Followers: {account['followers_count']}")
    
except Exception as e:
    print(f"\n❌ Login failed: {e}")
    print("\nAlternative method:")
    print(f"1. Go to: {instance}/settings/applications")
    print("2. Click on '{app_name}' or create new app")
    print("3. Copy the 'Your access token' value")
    exit(1)

# Step 4: Save to .env
print("\n" + "=" * 70)
print("STEP 4: Save configuration")
print("-" * 70)

env_file = ".env"
env_exists = os.path.exists(env_file)

print(f"\nYour access token:")
print("-" * 70)
print(access_token)
print("-" * 70)

if env_exists:
    print(f"\n✅ Found existing {env_file} file")
    update = input("Update .env file? [Y/n]: ").strip().lower()
    if update in ['', 'y', 'yes']:
        # Read existing content
        with open(env_file, 'r') as f:
            content = f.read()
        
        # Update or add Mastodon settings
        if 'MASTODON_INSTANCE=' in content:
            import re
            content = re.sub(
                r'MASTODON_INSTANCE=.*',
                f'MASTODON_INSTANCE={instance}',
                content
            )
            content = re.sub(
                r'MASTODON_ACCESS_TOKEN=.*',
                f'MASTODON_ACCESS_TOKEN={access_token}',
                content
            )
        else:
            # Append
            content += f"\n# Mastodon Configuration\n"
            content += f"MASTODON_INSTANCE={instance}\n"
            content += f"MASTODON_ACCESS_TOKEN={access_token}\n"
        
        with open(env_file, 'w') as f:
            f.write(content)
        
        print(f"✅ Updated {env_file}")
    else:
        print("\nSkipped. Add manually to .env:")
        print(f"MASTODON_INSTANCE={instance}")
        print(f"MASTODON_ACCESS_TOKEN={access_token}")
else:
    print(f"\n❌ {env_file} not found")
    print("\nCreate it with:")
    print(f"MASTODON_INSTANCE={instance}")
    print(f"MASTODON_ACCESS_TOKEN={access_token}")

# Step 5: Test
print("\n" + "=" * 70)
print("STEP 5: Test connection")
print("-" * 70)

test = input("\nTest streaming now? [Y/n]: ").strip().lower()
if test in ['', 'y', 'yes']:
    print("\nTesting stream for 10 seconds...\n")
    
    from mastodon import StreamListener
    import time
    
    class TestListener(StreamListener):
        def __init__(self):
            self.count = 0
        
        def on_update(self, status):
            self.count += 1
            account = status['account']
            print(f"{self.count}. @{account['username']}: {status['content'][:50]}...")
    
    listener = TestListener()
    
    try:
        # Start streaming in background
        import threading
        
        def stream_for_seconds(seconds):
            mastodon.stream_public(listener, run_async=False, timeout=seconds)
        
        thread = threading.Thread(target=stream_for_seconds, args=(10,))
        thread.daemon = True
        thread.start()
        thread.join(timeout=11)
        
        print(f"\n✅ Test complete! Received {listener.count} statuses")
        
    except Exception as e:
        print(f"\n⚠️  Test error: {e}")
        print("   But token should still work!")

print("\n" + "=" * 70)
print(" SETUP COMPLETE! ")
print("=" * 70)
print(f"\nInstance: {instance}")
print(f"Account: @{account['username']}")
print(f"\nRun the stream collector:")
print("  python3 mastodon_stream.py")
print("\nOr import in your code:")
print("  from mastodon import Mastodon")
print(f"  mastodon = Mastodon(")
print(f"      access_token='{access_token}',")
print(f"      api_base_url='{instance}'")
print(f"  )")
print("=" * 70)
