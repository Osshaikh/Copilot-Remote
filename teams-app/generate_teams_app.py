#!/usr/bin/env python3
"""
generate_teams_app.py — Build the Microsoft Teams app package (local-pilot.zip)

Usage:
    python teams-app/generate_teams_app.py \
        --app-id YOUR_MICROSOFT_APP_ID \
        --ngrok-url YOUR_NGROK_URL

This will:
  1. Fill in manifest.json with your credentials
  2. Generate the bot icons
  3. Package everything into local-pilot.zip ready to sideload into Teams
"""

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent


def generate_icons():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Installing Pillow...")
        os.system(f"{sys.executable} -m pip install Pillow --quiet")
        from PIL import Image, ImageDraw

    # Color icon 192x192
    img = Image.new("RGB", (192, 192), color="#6264A7")
    draw = ImageDraw.Draw(img)
    draw.ellipse([40, 30, 152, 142], fill="white")
    draw.ellipse([65, 60, 95, 90], fill="#6264A7")
    draw.ellipse([97, 60, 127, 90], fill="#6264A7")
    draw.rectangle([75, 100, 117, 112], fill="#6264A7")
    draw.text((55, 148), "local-pilot", fill="white")
    img.save(HERE / "color.png")

    # Outline icon 32x32
    outline = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw2 = ImageDraw.Draw(outline)
    draw2.ellipse([2, 2, 30, 30], outline="white", width=2)
    draw2.ellipse([8, 9, 14, 15], fill="white")
    draw2.ellipse([18, 9, 24, 15], fill="white")
    draw2.rectangle([10, 19, 22, 22], fill="white")
    outline.save(HERE / "outline.png")

    print("✓ Icons generated")


def build_zip(app_id: str, ngrok_url: str):
    ngrok_url = ngrok_url.replace("https://", "").replace("http://", "").rstrip("/")

    # Load and fill manifest
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest_str = json.dumps(manifest, indent=2) \
        .replace("YOUR_MICROSOFT_APP_ID", app_id) \
        .replace("YOUR_NGROK_URL", ngrok_url)

    # Generate icons
    generate_icons()

    # Write zip
    output = HERE / "local-pilot.zip"
    with zipfile.ZipFile(output, "w") as zf:
        zf.writestr("manifest.json", manifest_str)
        zf.write(HERE / "color.png", "color.png")
        zf.write(HERE / "outline.png", "outline.png")

    print(f"✓ Package built: {output}")
    print("\nNext steps:")
    print("  1. In Teams → Apps → Manage your apps → Upload an app → Upload a custom app")
    print(f"  2. Select: {output}")
    print("  3. Click Add — done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Teams app package for local-pilot")
    parser.add_argument("--app-id", required=True, help="Your Microsoft App ID (UUID from Azure Bot)")
    parser.add_argument("--ngrok-url", required=True, help="Your ngrok URL (e.g. https://abc123.ngrok-free.app)")
    args = parser.parse_args()
    build_zip(args.app_id, args.ngrok_url)
