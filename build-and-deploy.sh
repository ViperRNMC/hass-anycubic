#!/bin/zsh
# Build and deploy dynamic-prices-card to Home Assistant

rsync -av --delete ./custom_components/anycubic/ ~/hass-dev/custom_components/anycubic/

echo "\033[1;32m✅ Deploy complete.\033[0m"
