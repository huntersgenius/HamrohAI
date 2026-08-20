/// Repositories: one thin layer over the API, returning typed models.
///
/// Each method maps to exactly one endpoint. Business rules live on the server;
/// nothing here re-implements an access check, because the client is never the
/// place a medical isolation rule can be enforced.
library;

import '../../core/network/api_client.dart';
import '../models/models.dart';

class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<OtpChallenge> startPhoneAuth(String phone, String locale) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/auth/phone/start',
      body: <String, dynamic>{'phone': phone, 'locale': locale},
      skipAuth: true,
    );
    return OtpChallenge.fromJson(json);
  }

  /// Verify the SMS code. Passing [onboardingToken] links a Google/Telegram
  /// sign-in to whichever account owns this phone number.
  Future<SessionResponse> verifyPhone({
    required String challengeId,
    required String code,
    String? onboardingToken,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/auth/phone/verify',
      body: <String, dynamic>{
        'challenge_id': challengeId,
        'code': code,
        if (onboardingToken != null) 'onboarding_token': onboardingToken,
      },
      skipAuth: true,
    );
    return SessionResponse.fromJson(json);
  }

  Future<SessionResponse> signInWithGoogle(String idToken, String locale) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/auth/google',
      body: <String, dynamic>{'id_token': idToken, 'locale': locale},
      skipAuth: true,
    );
    return SessionResponse.fromJson(json);
  }

  Future<SessionResponse> signInWithTelegram(
    Map<String, dynamic> payload,
    String locale,
  ) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/auth/telegram',
      body: <String, dynamic>{...payload, 'locale': locale},
      skipAuth: true,
    );
    return SessionResponse.fromJson(json);
  }

  Future<AppUser> me() async => AppUser.fromJson(await _api.getJson('/auth/me'));

  Future<AuthState> state() async =>
      AuthState.fromJson(await _api.getJson('/auth/state'));

  Future<SessionResponse> selectRole(String role) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/auth/role',
      body: <String, dynamic>{'role': role},
    );
    return SessionResponse.fromJson(json);
  }

  Future<AppUser> updateMe(Map<String, dynamic> changes) async =>
      AppUser.fromJson(await _api.patchJson('/auth/me', body: changes));

  Future<void> registerDevice({
    required String token,
    required String platform,
    required String locale,
    String? appVersion,
  }) =>
      _api.postJson(
        '/auth/devices',
        body: <String, dynamic>{
          'token': token,
          'platform': platform,
          'locale': locale,
          if (appVersion != null) 'app_version': appVersion,
        },
      );

  Future<void> logout({String? refreshToken, String? deviceToken}) => _api.postJson(
        '/auth/logout',
        body: <String, dynamic>{
          if (refreshToken != null) 'refresh_token': refreshToken,
          if (deviceToken != null) 'device_token': deviceToken,
        },
      );
}

class DoctorRepository {
  DoctorRepository(this._api);

  final ApiClient _api;

  Future<List<SpecialtyOption>> specialties() async {
    final List<dynamic> raw = await _api.getList('/doctors/specialties');
    return raw
        .map((dynamic e) => SpecialtyOption.fromJson(
            (e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<DoctorProfile> register({
    required String fullName,
    required String specialty,
    required int experienceYears,
    required String licenseDocumentId,
    int? age,
    String? bio,
    String? workplace,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/doctors/register',
      body: <String, dynamic>{
        'full_name': fullName,
        'specialty': specialty,
        'experience_years': experienceYears,
        'license_document_id': licenseDocumentId,
        if (age != null) 'age': age,
        if (bio != null) 'bio': bio,
        if (workplace != null) 'workplace': workplace,
      },
    );
    return DoctorProfile.fromJson(json);
  }

  Future<DoctorProfile> me() async =>
      DoctorProfile.fromJson(await _api.getJson('/doctors/me'));

  Future<DoctorProfile> updateProfile(Map<String, dynamic> changes) async =>
      DoctorProfile.fromJson(await _api.patchJson('/doctors/me', body: changes));

  Future<DoctorProfile> updateConsultationSettings(
    Map<String, dynamic> changes,
  ) async =>
      DoctorProfile.fromJson(
        await _api.patchJson('/doctors/me/consultation-settings', body: changes),
      );

  Future<Paged<PatientListItem>> patients({
    int limit = 20,
    int offset = 0,
    String? search,
  }) async {
    final Map<String, dynamic> json = await _api.getJson(
      '/doctors/me/patients',
      query: <String, dynamic>{
        'limit': limit,
        'offset': offset,
        if (search != null && search.isNotEmpty) 'search': search,
      },
    );
    return Paged<PatientListItem>.fromJson(json, PatientListItem.fromJson);
  }

  Future<PatientInvite> createInvite({
    required String fullName,
    required String phone,
    String? diagnosisText,
    String? templateId,
    List<String> documentIds = const <String>[],
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/doctors/me/invites',
      body: <String, dynamic>{
        'full_name': fullName,
        'phone': phone,
        if (diagnosisText != null && diagnosisText.isNotEmpty)
          'diagnosis_text': diagnosisText,
        if (templateId != null) 'template_id': templateId,
        'document_ids': documentIds,
      },
    );
    return PatientInvite.fromJson(json);
  }

  Future<List<PatientInvite>> invites() async {
    final List<dynamic> raw = await _api.getList('/doctors/me/invites');
    return raw
        .map((dynamic e) =>
            PatientInvite.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<void> revokeInvite(String id) => _api.delete('/doctors/me/invites/$id');

  Future<List<DoctorSearchItem>> search({String? query, String? specialty}) async {
    final List<dynamic> raw = await _api.getList(
      '/doctors/search',
      query: <String, dynamic>{
        if (query != null && query.isNotEmpty) 'q': query,
        if (specialty != null) 'specialty': specialty,
      },
    );
    return raw
        .map((dynamic e) => DoctorSearchItem.fromJson(
            (e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }
}

class PatientRepository {
  PatientRepository(this._api);

  final ApiClient _api;

  Future<Map<String, dynamic>> register({
    required String fullName,
    DateTime? birthDate,
    String? gender,
    String? region,
    String? notes,
  }) =>
      _api.postJson(
        '/patients/register',
        body: <String, dynamic>{
          'full_name': fullName,
          if (birthDate != null)
            'birth_date': birthDate.toIso8601String().split('T').first,
          if (gender != null) 'gender': gender,
          if (region != null) 'region': region,
          if (notes != null) 'notes': notes,
        },
      );

  Future<Map<String, dynamic>> me() => _api.getJson('/patients/me');

  Future<Map<String, dynamic>> update(Map<String, dynamic> changes) =>
      _api.patchJson('/patients/me', body: changes);

  Future<ThreadDocument> uploadDocument({
    required String filePath,
    required String filename,
    String purpose = 'care_thread',
  }) async {
    final Map<String, dynamic> json = await _api.uploadFile(
      '/documents',
      filePath: filePath,
      filename: filename,
      fields: <String, dynamic>{'purpose': purpose},
    );
    return ThreadDocument.fromJson(json);
  }
}

class ThreadRepository {
  ThreadRepository(this._api);

  final ApiClient _api;

  Future<List<CareThread>> list({bool includePersonal = true}) async {
    final List<dynamic> raw = await _api.getList(
      '/threads',
      query: <String, dynamic>{'include_personal': includePersonal},
    );
    return raw
        .map((dynamic e) =>
            CareThread.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<CareThread> personal() async =>
      CareThread.fromJson(await _api.getJson('/threads/personal'));

  Future<CareThread> get(String id) async =>
      CareThread.fromJson(await _api.getJson('/threads/$id'));

  /// Redeem either a one-time invite code or a doctor's permanent connect code.
  Future<Map<String, dynamic>> connect(String code) =>
      _api.postJson('/threads/connect', body: <String, dynamic>{'code': code});

  Future<void> sharePersonal({
    required String targetThreadId,
    required String sourceThreadId,
  }) =>
      _api.postJson(
        '/threads/$targetThreadId/share-personal',
        body: <String, dynamic>{
          'source_thread_id': sourceThreadId,
          'consent': true,
        },
      );

  // ----------------------------------------------------------- diagnoses
  Future<List<Diagnosis>> diagnoses(String threadId) async {
    final List<dynamic> raw = await _api.getList('/threads/$threadId/diagnoses');
    return raw
        .map((dynamic e) =>
            Diagnosis.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<Diagnosis> createDiagnosis(
    String threadId, {
    required String text,
    String? templateId,
    String? notes,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/threads/$threadId/diagnoses',
      body: <String, dynamic>{
        'text': text,
        if (templateId != null) 'template_id': templateId,
        if (notes != null) 'notes': notes,
        'auto_match_template': templateId == null,
      },
    );
    return Diagnosis.fromJson(json);
  }

  Future<Diagnosis> updateDiagnosis(
    String threadId,
    String diagnosisId, {
    required String text,
    String? templateId,
    String? notes,
  }) async {
    final Map<String, dynamic> json = await _api.patchJson(
      '/threads/$threadId/diagnoses/$diagnosisId',
      body: <String, dynamic>{
        'text': text,
        if (templateId != null) 'template_id': templateId,
        if (notes != null) 'notes': notes,
      },
    );
    return Diagnosis.fromJson(json);
  }

  Future<Diagnosis> verifyDiagnosis(String threadId, String diagnosisId) async =>
      Diagnosis.fromJson(
        await _api.postJson('/threads/$threadId/diagnoses/$diagnosisId/verify'),
      );

  /// The patient's only route to a verified diagnosis (spec 2.3).
  Future<ChangeRequest> proposeChange(
    String threadId,
    String diagnosisId, {
    required String comment,
    String? proposedText,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/threads/$threadId/diagnoses/$diagnosisId/change-requests',
      body: <String, dynamic>{
        'comment': comment,
        if (proposedText != null && proposedText.isNotEmpty)
          'proposed_text': proposedText,
      },
    );
    return ChangeRequest.fromJson(json);
  }

  Future<ChangeRequest> resolveChange(
    String threadId,
    String requestId, {
    required bool accept,
    String? resolutionNote,
    String? finalText,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/threads/$threadId/change-requests/$requestId/resolve',
      body: <String, dynamic>{
        'accept': accept,
        if (resolutionNote != null) 'resolution_note': resolutionNote,
        if (finalText != null) 'final_text': finalText,
      },
    );
    return ChangeRequest.fromJson(json);
  }

  // ----------------------------------------------------------- templates
  Future<List<DiagnosisTemplate>> templates() async {
    final List<dynamic> raw = await _api.getList('/threads/templates/all');
    return raw
        .map((dynamic e) => DiagnosisTemplate.fromJson(
            (e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  /// Ask the server which template the typed diagnosis maps to (spec 6).
  Future<TemplateMatch> matchTemplate(String text) async => TemplateMatch.fromJson(
        await _api.postJson(
          '/threads/templates/match',
          body: <String, dynamic>{'text': text},
        ),
      );

  // --------------------------------------------------------- medications
  Future<List<Medication>> medications(String threadId) async {
    final List<dynamic> raw = await _api.getList('/threads/$threadId/medications');
    return raw
        .map((dynamic e) =>
            Medication.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<Medication> createMedication(
    String threadId, {
    required String name,
    required String dose,
    required List<String> times,
    String? instructions,
    List<int> weekdays = const <int>[],
    DateTime? endsOn,
  }) async {
    final Map<String, dynamic> json = await _api.postJson(
      '/threads/$threadId/medications',
      body: <String, dynamic>{
        'name': name,
        'dose': dose,
        'times': times,
        'weekdays': weekdays,
        if (instructions != null) 'instructions': instructions,
        if (endsOn != null) 'ends_on': endsOn.toIso8601String().split('T').first,
      },
    );
    return Medication.fromJson(json);
  }

  Future<Medication> updateMedication(
    String threadId,
    String medicationId,
    Map<String, dynamic> changes,
  ) async =>
      Medication.fromJson(
        await _api.patchJson(
          '/threads/$threadId/medications/$medicationId',
          body: changes,
        ),
      );

  Future<void> deleteMedication(String threadId, String medicationId) =>
      _api.delete('/threads/$threadId/medications/$medicationId');

  Future<List<MedicationDose>> doses(String threadId, {DateTime? day}) async {
    final List<dynamic> raw = await _api.getList(
      '/threads/$threadId/doses',
      query: <String, dynamic>{
        if (day != null) 'day': day.toIso8601String().split('T').first,
      },
    );
    return raw
        .map((dynamic e) =>
            MedicationDose.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  /// The "Ichdim ✓" action.
  Future<MedicationDose> markDoseTaken(String threadId, String doseId) async =>
      MedicationDose.fromJson(
        await _api.postJson('/threads/$threadId/doses/$doseId/taken'),
      );

  // -------------------------------------------------------------- metrics
  Future<List<MetricSeries>> series(String threadId) async {
    final List<dynamic> raw = await _api.getList('/threads/$threadId/series');
    return raw
        .map((dynamic e) =>
            MetricSeries.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<TrendData> trend(
    String threadId,
    String seriesId, {
    int days = 30,
  }) async =>
      TrendData.fromJson(
        await _api.getJson(
          '/threads/$threadId/series/$seriesId/trend',
          query: <String, dynamic>{'days': days},
        ),
      );

  Future<void> addReading(
    String threadId,
    String seriesId, {
    required double value,
    double? valueSecondary,
    DateTime? recordedAt,
    String? note,
  }) =>
      _api.postJson(
        '/threads/$threadId/series/$seriesId/readings',
        body: <String, dynamic>{
          'value': value,
          if (valueSecondary != null) 'value_secondary': valueSecondary,
          if (recordedAt != null) 'recorded_at': recordedAt.toUtc().toIso8601String(),
          if (note != null) 'note': note,
        },
      );

  Future<List<int>> exportSeries(
    String threadId,
    String seriesId, {
    int days = 180,
  }) =>
      _api.downloadBytes(
        '/threads/$threadId/series/$seriesId/export',
        query: <String, dynamic>{'days': days},
      );

  /// Doctor-only (spec 5.2 tab 2).
  Future<Map<String, dynamic>> importSeries(
    String threadId,
    String seriesId, {
    required String filePath,
    required String filename,
  }) =>
      _api.uploadFile(
        '/threads/$threadId/series/$seriesId/import',
        filePath: filePath,
        filename: filename,
      );

  // ------------------------------------------------------------- check-in
  Future<TodayData> today(String threadId, {String slot = 'day'}) async =>
      TodayData.fromJson(
        await _api.getJson(
          '/threads/$threadId/today',
          query: <String, dynamic>{'slot': slot},
        ),
      );

  Future<void> submitCheckin(
    String threadId, {
    required Map<String, dynamic> answers,
    String slot = 'day',
  }) =>
      _api.postJson(
        '/threads/$threadId/checkins',
        body: <String, dynamic>{'answers': answers, 'slot': slot},
      );

  // ------------------------------------------------------------ documents
  Future<List<ThreadDocument>> documents(String threadId) async {
    final List<dynamic> raw = await _api.getList('/threads/$threadId/documents');
    return raw
        .map((dynamic e) =>
            ThreadDocument.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<ThreadDocument> uploadDocument(
    String threadId, {
    required String filePath,
    required String filename,
  }) async =>
      ThreadDocument.fromJson(
        await _api.uploadFile(
          '/threads/$threadId/documents',
          filePath: filePath,
          filename: filename,
        ),
      );
}

class ConsultationRepository {
  ConsultationRepository(this._api);

  final ApiClient _api;

  Future<PriceQuote> quote({String? specialty, String? doctorUserId}) async =>
      PriceQuote.fromJson(
        await _api.getJson(
          '/consultations/quote',
          query: <String, dynamic>{
            if (specialty != null) 'specialty': specialty,
            if (doctorUserId != null) 'doctor_user_id': doctorUserId,
          },
        ),
      );

  Future<Map<String, dynamic>> create({
    String? doctorUserId,
    String? specialty,
    required String question,
    String? careThreadId,
    bool shareClinicalData = true,
    required String paymentProvider,
    List<String> attachmentIds = const <String>[],
  }) =>
      _api.postJson(
        '/consultations',
        body: <String, dynamic>{
          if (doctorUserId != null) 'doctor_user_id': doctorUserId,
          if (specialty != null) 'specialty': specialty,
          'question': question,
          if (careThreadId != null) 'care_thread_id': careThreadId,
          'share_clinical_data': shareClinicalData,
          'payment_provider': paymentProvider,
          'attachment_ids': attachmentIds,
        },
      );

  Future<Paged<Consultation>> mine({int limit = 20, int offset = 0}) async =>
      Paged<Consultation>.fromJson(
        await _api.getJson(
          '/consultations/mine',
          query: <String, dynamic>{'limit': limit, 'offset': offset},
        ),
        Consultation.fromJson,
      );

  Future<Paged<ConsultationListItem>> inbox({
    int limit = 20,
    int offset = 0,
  }) async =>
      Paged<ConsultationListItem>.fromJson(
        await _api.getJson(
          '/consultations/inbox',
          query: <String, dynamic>{'limit': limit, 'offset': offset},
        ),
        ConsultationListItem.fromJson,
      );

  Future<Paged<ConsultationListItem>> history({
    int limit = 20,
    int offset = 0,
  }) async =>
      Paged<ConsultationListItem>.fromJson(
        await _api.getJson(
          '/consultations/history',
          query: <String, dynamic>{'limit': limit, 'offset': offset},
        ),
        ConsultationListItem.fromJson,
      );

  Future<Consultation> get(String id) async =>
      Consultation.fromJson(await _api.getJson('/consultations/$id'));

  /// "Qabul qilish" — exclusive; a 409 means another doctor won the race.
  Future<Consultation> claim(String id) async =>
      Consultation.fromJson(await _api.postJson('/consultations/$id/claim'));

  Future<Consultation> answer(String id, String text) async => Consultation.fromJson(
        await _api.postJson(
          '/consultations/$id/answer',
          body: <String, dynamic>{'answer_text': text},
        ),
      );

  Future<Consultation> rate(String id, int rating, String? review) async =>
      Consultation.fromJson(
        await _api.postJson(
          '/consultations/$id/rate',
          body: <String, dynamic>{
            'rating': rating,
            if (review != null && review.isNotEmpty) 'review': review,
          },
        ),
      );
}

class AiRepository {
  AiRepository(this._api);

  final ApiClient _api;

  Future<AiReply> ask({required String message, String? careThreadId}) async =>
      AiReply.fromJson(
        await _api.postJson(
          '/ai/ask',
          body: <String, dynamic>{
            'message': message,
            if (careThreadId != null) 'care_thread_id': careThreadId,
          },
        ),
      );

  Future<List<AiMessage>> messages(String threadId, {int limit = 50}) async {
    final List<dynamic> raw = await _api.getList(
      '/ai/threads/$threadId/messages',
      query: <String, dynamic>{'limit': limit},
    );
    return raw
        .map((dynamic e) =>
            AiMessage.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<Paged<Escalation>> escalations({bool openOnly = true}) async =>
      Paged<Escalation>.fromJson(
        await _api.getJson(
          '/ai/escalations',
          query: <String, dynamic>{'open_only': openOnly},
        ),
        Escalation.fromJson,
      );

  Future<Escalation> answerEscalation(String id, String text) async =>
      Escalation.fromJson(
        await _api.postJson(
          '/ai/escalations/$id/answer',
          body: <String, dynamic>{'answer_text': text},
        ),
      );

  Future<List<WeeklyReport>> weeklyReports(String threadId) async {
    final List<dynamic> raw = await _api.getList('/ai/threads/$threadId/weekly-reports');
    return raw
        .map((dynamic e) =>
            WeeklyReport.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<Map<String, dynamic>> weeklyPreview(String threadId) =>
      _api.getJson('/ai/threads/$threadId/weekly-preview');
}

class NotificationRepository {
  NotificationRepository(this._api);

  final ApiClient _api;

  Future<Paged<AppNotification>> list({int limit = 30, int offset = 0}) async =>
      Paged<AppNotification>.fromJson(
        await _api.getJson(
          '/notifications',
          query: <String, dynamic>{'limit': limit, 'offset': offset},
        ),
        AppNotification.fromJson,
      );

  Future<int> unreadCount() async {
    final Map<String, dynamic> json = await _api.getJson('/notifications/unread-count');
    final Object? count = json['count'];
    return count is int ? count : 0;
  }

  Future<void> markRead({List<String>? ids, bool all = false}) => _api.postJson(
        '/notifications/read',
        body: <String, dynamic>{if (ids != null) 'ids': ids, 'all': all},
      );
}

class BillingRepository {
  BillingRepository(this._api);

  final ApiClient _api;

  Future<Wallet> wallet() async => Wallet.fromJson(await _api.getJson('/wallet'));

  Future<Paged<WalletTransaction>> transactions({
    int limit = 30,
    int offset = 0,
  }) async =>
      Paged<WalletTransaction>.fromJson(
        await _api.getJson(
          '/wallet/transactions',
          query: <String, dynamic>{'limit': limit, 'offset': offset},
        ),
        WalletTransaction.fromJson,
      );

  Future<PayoutRequest> requestPayout({
    required int amountUzs,
    required String cardNumber,
    required String cardHolder,
  }) async =>
      PayoutRequest.fromJson(
        await _api.postJson(
          '/wallet/payouts',
          body: <String, dynamic>{
            'amount_uzs': amountUzs,
            'card_number': cardNumber,
            'card_holder': cardHolder,
          },
        ),
      );

  Future<List<PayoutRequest>> payouts() async {
    final List<dynamic> raw = await _api.getList('/wallet/payouts');
    return raw
        .map((dynamic e) =>
            PayoutRequest.fromJson((e as Map<dynamic, dynamic>).cast<String, dynamic>()))
        .toList();
  }

  Future<SubscriptionStatus> subscription() async =>
      SubscriptionStatus.fromJson(await _api.getJson('/subscription'));

  Future<CheckoutInfo> subscribe({
    required String plan,
    required String provider,
  }) async =>
      CheckoutInfo.fromJson(
        await _api.postJson(
          '/subscription/checkout',
          body: <String, dynamic>{'plan': plan, 'provider': provider},
        ),
      );
}
