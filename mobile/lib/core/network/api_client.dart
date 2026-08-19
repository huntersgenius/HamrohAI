import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/env.dart';
import 'api_exception.dart';
import 'token_storage.dart';

/// HTTP client for the Hamroh API.
///
/// Owns two things the rest of the app should never think about: attaching the
/// access token, and refreshing it exactly once when a request comes back 401.
/// Concurrent 401s share a single refresh future, so a screen with four
/// parallel requests does not fire four refreshes and invalidate its own
/// session through the server's token-reuse detection.
class ApiClient {
  ApiClient({required TokenStorage storage, Dio? dio})
      : _storage = storage,
        _dio = dio ?? Dio() {
    _dio.options = BaseOptions(
      baseUrl: Env.apiBaseUrl,
      connectTimeout: const Duration(seconds: 20),
      receiveTimeout: const Duration(seconds: 40),
      sendTimeout: const Duration(seconds: 40),
      headers: <String, String>{'Accept': 'application/json'},
      // Errors are converted below, so any status is a valid response here.
      validateStatus: (int? status) => status != null && status < 500,
    );
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: _onRequest,
        onError: _onError,
      ),
    );
    if (kDebugMode) {
      _dio.interceptors.add(
        LogInterceptor(requestBody: false, responseBody: false),
      );
    }
  }

  final Dio _dio;
  final TokenStorage _storage;

  /// Called when the session cannot be recovered; the app returns to sign-in.
  void Function()? onAuthFailure;

  Future<void>? _refreshInFlight;

  Dio get raw => _dio;

  Future<void> _onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (options.extra['skipAuth'] != true) {
      final String? token = await _storage.readAccessToken();
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }

  Future<void> _onError(
    DioException error,
    ErrorInterceptorHandler handler,
  ) async {
    handler.next(error);
  }

  Future<Response<dynamic>> _send(
    String method,
    String path, {
    Object? data,
    Map<String, dynamic>? query,
    bool skipAuth = false,
    bool isRetry = false,
    ResponseType? responseType,
  }) async {
    Response<dynamic> response;
    try {
      response = await _dio.request<dynamic>(
        path,
        data: data,
        queryParameters: query,
        options: Options(
          method: method,
          extra: <String, dynamic>{'skipAuth': skipAuth},
          responseType: responseType,
        ),
      );
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }

    if (response.statusCode == 401 && !skipAuth && !isRetry) {
      final bool refreshed = await _refreshOnce();
      if (refreshed) {
        return _send(
          method,
          path,
          data: data,
          query: query,
          isRetry: true,
          responseType: responseType,
        );
      }
      await _storage.clear();
      onAuthFailure?.call();
    }

    if (response.statusCode != null && response.statusCode! >= 400) {
      throw ApiException.fromResponse(response);
    }
    return response;
  }

  /// Refresh the session, collapsing concurrent callers onto one request.
  Future<bool> _refreshOnce() {
    final Future<void>? inFlight = _refreshInFlight;
    if (inFlight != null) {
      return inFlight.then((_) async => await _storage.readAccessToken() != null);
    }

    final Completer<void> completer = Completer<void>();
    _refreshInFlight = completer.future;

    return () async {
      try {
        final String? refreshToken = await _storage.readRefreshToken();
        if (refreshToken == null) return false;

        final Response<dynamic> response = await _dio.post<dynamic>(
          '/auth/refresh',
          data: <String, dynamic>{'refresh_token': refreshToken},
          options: Options(extra: <String, dynamic>{'skipAuth': true}),
        );
        if (response.statusCode != 200 || response.data is! Map) {
          return false;
        }
        final Map<String, dynamic> body =
            (response.data as Map<dynamic, dynamic>).cast<String, dynamic>();
        await _storage.saveTokens(
          accessToken: body['access_token'] as String,
          refreshToken: body['refresh_token'] as String,
        );
        return true;
      } catch (_) {
        return false;
      } finally {
        _refreshInFlight = null;
        completer.complete();
      }
    }();
  }

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? query,
    bool skipAuth = false,
  }) async {
    final Response<dynamic> response =
        await _send('GET', path, query: query, skipAuth: skipAuth);
    return _asMap(response.data);
  }

  Future<List<dynamic>> getList(
    String path, {
    Map<String, dynamic>? query,
    bool skipAuth = false,
  }) async {
    final Response<dynamic> response =
        await _send('GET', path, query: query, skipAuth: skipAuth);
    final dynamic data = response.data;
    if (data is List) return data;
    if (data is Map && data['items'] is List) return data['items'] as List<dynamic>;
    return <dynamic>[];
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool skipAuth = false,
  }) async {
    final Response<dynamic> response = await _send(
      'POST',
      path,
      data: body,
      query: query,
      skipAuth: skipAuth,
    );
    return _asMap(response.data);
  }

  Future<Map<String, dynamic>> patchJson(
    String path, {
    Object? body,
  }) async {
    final Response<dynamic> response = await _send('PATCH', path, data: body);
    return _asMap(response.data);
  }

  Future<void> delete(String path) => _send('DELETE', path);

  /// Multipart upload used for licence documents, thread files and Excel import.
  Future<Map<String, dynamic>> uploadFile(
    String path, {
    required String filePath,
    required String filename,
    Map<String, dynamic>? fields,
  }) async {
    final FormData form = FormData.fromMap(<String, dynamic>{
      ...?fields,
      'file': await MultipartFile.fromFile(filePath, filename: filename),
    });
    final Response<dynamic> response = await _send('POST', path, data: form);
    return _asMap(response.data);
  }

  /// Raw bytes, for the Excel export endpoint.
  Future<List<int>> downloadBytes(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    final Response<dynamic> response = await _send(
      'GET',
      path,
      query: query,
      responseType: ResponseType.bytes,
    );
    final dynamic data = response.data;
    if (data is List<int>) return data;
    return <int>[];
  }

  Map<String, dynamic> _asMap(dynamic data) {
    if (data is Map) return data.cast<String, dynamic>();
    return <String, dynamic>{};
  }
}
