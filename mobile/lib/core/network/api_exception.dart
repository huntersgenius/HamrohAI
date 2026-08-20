import 'package:dio/dio.dart';

/// A failure the UI can act on.
///
/// The server returns a stable machine-readable `code`; the app localizes on
/// that rather than on the server's message, so error text follows the user's
/// chosen language even when the API replies in another.
class ApiException implements Exception {
  ApiException({
    required this.code,
    required this.message,
    this.statusCode,
    this.details = const <String, dynamic>{},
  });

  factory ApiException.fromResponse(Response<dynamic> response) {
    final dynamic data = response.data;
    if (data is Map && data['code'] is String) {
      return ApiException(
        code: data['code'] as String,
        message: (data['message'] as String?) ?? 'error',
        statusCode: response.statusCode,
        details: data['details'] is Map
            ? (data['details'] as Map<dynamic, dynamic>).cast<String, dynamic>()
            : const <String, dynamic>{},
      );
    }
    return ApiException(
      code: _codeForStatus(response.statusCode),
      message: 'request failed',
      statusCode: response.statusCode,
    );
  }

  factory ApiException.fromDio(DioException error) {
    if (error.response != null) {
      return ApiException.fromResponse(error.response!);
    }
    final bool isTimeout = error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.receiveTimeout ||
        error.type == DioExceptionType.sendTimeout;
    return ApiException(
      code: isTimeout ? 'timeout' : 'network_error',
      message: error.message ?? 'network error',
    );
  }

  final String code;
  final String message;
  final int? statusCode;
  final Map<String, dynamic> details;

  bool get isNetwork => code == 'network_error' || code == 'timeout';
  bool get isUnauthorized => statusCode == 401;

  /// Localization key for this failure, falling back to a generic message.
  String get l10nKey {
    const Set<String> known = <String>{
      'code_not_found',
      'code_used',
      'code_phone_mismatch',
      'already_connected',
      'already_claimed',
      'subscription_required',
      'doctor_not_verified',
      'otp_cooldown',
      'insufficient_balance',
      'payout_below_minimum',
      'validation_error',
      'invalid_phone',
      'phone_invalid',
    };
    if (code == 'network_error' || code == 'timeout') return 'error.network';
    if (code == 'validation_error') return 'error.validation';
    if (code == 'phone_invalid' || code == 'invalid_phone') {
      return 'error.invalid_phone';
    }
    if (known.contains(code)) return 'error.$code';
    if (statusCode == 401) return 'error.unauthorized';
    if (statusCode == 403) return 'error.forbidden';
    if (statusCode == 404) return 'error.not_found';
    if ((statusCode ?? 500) >= 500) return 'error.server';
    return 'common.error';
  }

  static String _codeForStatus(int? status) => switch (status) {
        400 => 'bad_request',
        401 => 'unauthorized',
        403 => 'forbidden',
        404 => 'not_found',
        409 => 'conflict',
        422 => 'validation_error',
        429 => 'rate_limited',
        _ => 'server_error',
      };

  @override
  String toString() => 'ApiException($code, $statusCode): $message';
}
