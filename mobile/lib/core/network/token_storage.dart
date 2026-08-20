import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Session tokens, held in the platform keychain / EncryptedSharedPreferences.
///
/// Nothing clinical is cached on the device: only tokens and the chosen locale.
/// A lost or stolen phone therefore exposes no medical history once the session
/// is revoked server-side.
class TokenStorage {
  TokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  static const String _accessKey = 'hamroh.access_token';
  static const String _refreshKey = 'hamroh.refresh_token';
  static const String _localeKey = 'hamroh.locale';

  final FlutterSecureStorage _storage;

  // Cached in memory so the request interceptor avoids a keychain read per call.
  String? _accessCache;

  Future<String?> readAccessToken() async {
    _accessCache ??= await _storage.read(key: _accessKey);
    return _accessCache;
  }

  Future<String?> readRefreshToken() => _storage.read(key: _refreshKey);

  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    _accessCache = accessToken;
    await _storage.write(key: _accessKey, value: accessToken);
    await _storage.write(key: _refreshKey, value: refreshToken);
  }

  Future<void> clear() async {
    _accessCache = null;
    await _storage.delete(key: _accessKey);
    await _storage.delete(key: _refreshKey);
  }

  Future<bool> get hasSession async => await readRefreshToken() != null;

  Future<String?> readLocale() => _storage.read(key: _localeKey);

  Future<void> saveLocale(String code) => _storage.write(key: _localeKey, value: code);
}
