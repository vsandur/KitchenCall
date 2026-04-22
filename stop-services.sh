#!/usr/bin/env bash
# Stop all KitchenCall services

echo "==> Stopping KitchenCall services..."

pkill -f "uvicorn app.main:app" && echo "  ✓ Stopped API" || echo "  - API not running"
pkill -f "personaplex_mlx.local_web" && echo "  ✓ Stopped PersonaPlex" || echo "  - PersonaPlex not running"
pkill -f "cloudflared tunnel --url" && echo "  ✓ Stopped tunnel" || echo "  - Tunnel not running"

sleep 1

echo "==> Services stopped"
