/// Build-time configuration.
///
/// Values come from `--dart-define` so a release build never carries a
/// development endpoint. The default points at the local backend.
class Env {
  const Env._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );

  static const String telegramBotName = String.fromEnvironment(
    'TELEGRAM_BOT_NAME',
    defaultValue: 'hamroh_bot',
  );

  static const String googleServerClientId = String.fromEnvironment(
    'GOOGLE_SERVER_CLIENT_ID',
    defaultValue: '',
  );

  static const String appStoreUrl = String.fromEnvironment(
    'APP_STORE_URL',
    defaultValue: 'https://hamroh.uz/app',
  );

  static const bool isProduction = bool.fromEnvironment('PRODUCTION');
}
