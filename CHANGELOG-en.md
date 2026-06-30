# Omoda / Jaecoo English Fork Changelog

## v1.5.22-EN

**Initial English Fork Release & Complete Localization**

- **Domain Rename**: Completely renamed the integration domain from `omoda9` to `omoda_jaecoo` to better reflect support for Jaecoo vehicles and the shared app platform.
- **English Native**: Translated all default entity names, binary sensors, buttons, and switches from Italian to English.
- **Dynamic Translation Keys**: Reworked all entity lookup strings to use standard `snake_case` english keys.
- **Backward Compatibility**: Injected all legacy Italian entity translation strings as fallbacks into the English dictionary so that existing users upgrading to this fork will seamlessly transition without broken dashboard names.
- **Automation Blueprint**: Renamed and translated the `failed_command.yaml` blueprint into English.
- **Web API**: Forced HTTP requests to the Omoda backend to use the `"Accept-Language": "en-GB"` header so that OTP codes and emails are dispatched in English.
