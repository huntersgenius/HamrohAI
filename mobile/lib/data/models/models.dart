/// API data models.
///
/// Hand-written `fromJson` rather than generated code: the project stays
/// buildable without `build_runner`, and every parser tolerates a missing or
/// null field instead of throwing inside a widget build.
library;

// ---------------------------------------------------------------- helpers
int _asInt(Object? value, [int fallback = 0]) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? fallback;
  return fallback;
}

double? _asDouble(Object? value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

bool _asBool(Object? value, [bool fallback = false]) {
  if (value is bool) return value;
  if (value is String) return value.toLowerCase() == 'true';
  return fallback;
}

DateTime? _asDate(Object? value) {
  if (value is String && value.isNotEmpty) return DateTime.tryParse(value)?.toLocal();
  return null;
}

Map<String, dynamic> _asMap(Object? value) {
  if (value is Map) return value.cast<String, dynamic>();
  return <String, dynamic>{};
}

List<Map<String, dynamic>> _asMapList(Object? value) {
  if (value is List) {
    return value
        .whereType<Map<dynamic, dynamic>>()
        .map((Map<dynamic, dynamic> e) => e.cast<String, dynamic>())
        .toList();
  }
  return <Map<String, dynamic>>[];
}

List<String> _asStringList(Object? value) {
  if (value is List) return value.map((Object? e) => '$e').toList();
  return <String>[];
}

// ------------------------------------------------------------------- auth
class AuthState {
  const AuthState({
    required this.phoneVerificationRequired,
    required this.roleSelectionRequired,
    required this.profileSetupRequired,
    this.role,
  });

  factory AuthState.fromJson(Map<String, dynamic> json) => AuthState(
        phoneVerificationRequired: _asBool(json['phone_verification_required'], true),
        roleSelectionRequired: _asBool(json['role_selection_required'], true),
        profileSetupRequired: _asBool(json['profile_setup_required'], true),
        role: json['role'] as String?,
      );

  final bool phoneVerificationRequired;
  final bool roleSelectionRequired;
  final bool profileSetupRequired;
  final String? role;

  bool get isDoctor => role == 'doctor';
  bool get isPatient => role == 'patient';

  /// True when onboarding is finished and the main tabs can be shown.
  bool get isComplete =>
      !phoneVerificationRequired && !roleSelectionRequired && !profileSetupRequired;
}

class SessionResponse {
  const SessionResponse({
    required this.state,
    this.accessToken,
    this.refreshToken,
    this.onboardingToken,
    this.user,
  });

  factory SessionResponse.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> tokens = _asMap(json['tokens']);
    return SessionResponse(
      state: AuthState.fromJson(_asMap(json['state'])),
      accessToken: tokens['access_token'] as String?,
      refreshToken: tokens['refresh_token'] as String?,
      onboardingToken: json['onboarding_token'] as String?,
      user: json['user'] == null ? null : AppUser.fromJson(_asMap(json['user'])),
    );
  }

  final AuthState state;
  final String? accessToken;
  final String? refreshToken;

  /// Present when the provider sign-in succeeded but the phone is not verified.
  final String? onboardingToken;
  final AppUser? user;

  bool get hasSession => accessToken != null && refreshToken != null;
}

class AppUser {
  const AppUser({
    required this.id,
    required this.phone,
    required this.locale,
    this.fullName,
    this.role,
    this.birthDate,
    this.email,
    this.avatarUrl,
    this.notifyPushEnabled = true,
    this.notifyPreferences = const <String, dynamic>{},
    this.ivrRemindersEnabled = true,
  });

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: '${json['id']}',
        phone: '${json['phone']}',
        locale: (json['locale'] as String?) ?? 'uz',
        fullName: json['full_name'] as String?,
        role: json['role'] as String?,
        birthDate: _asDate(json['birth_date']),
        email: json['email'] as String?,
        avatarUrl: json['avatar_url'] as String?,
        notifyPushEnabled: _asBool(json['notify_push_enabled'], true),
        notifyPreferences: _asMap(json['notify_preferences']),
        ivrRemindersEnabled: _asBool(json['ivr_reminders_enabled'], true),
      );

  final String id;
  final String phone;
  final String locale;
  final String? fullName;
  final String? role;
  final DateTime? birthDate;
  final String? email;
  final String? avatarUrl;
  final bool notifyPushEnabled;
  final Map<String, dynamic> notifyPreferences;
  final bool ivrRemindersEnabled;

  bool prefers(String key, {bool fallback = true}) {
    if (!notifyPushEnabled) return false;
    final Object? value = notifyPreferences[key];
    return value is bool ? value : fallback;
  }
}

class OtpChallenge {
  const OtpChallenge({
    required this.challengeId,
    required this.expiresAt,
    required this.resendAvailableAt,
    this.debugCode,
  });

  factory OtpChallenge.fromJson(Map<String, dynamic> json) => OtpChallenge(
        challengeId: '${json['challenge_id']}',
        expiresAt: _asDate(json['expires_at']) ?? DateTime.now(),
        resendAvailableAt: _asDate(json['resend_available_at']) ?? DateTime.now(),
        debugCode: json['debug_code'] as String?,
      );

  final String challengeId;
  final DateTime expiresAt;
  final DateTime resendAvailableAt;

  /// Only populated outside production, to make local testing possible.
  final String? debugCode;
}

// ----------------------------------------------------------------- doctor
class DoctorProfile {
  const DoctorProfile({
    required this.id,
    required this.userId,
    required this.fullName,
    required this.specialty,
    required this.experienceYears,
    required this.verificationStatus,
    required this.connectCode,
    required this.consultationOpen,
    this.age,
    this.bio,
    this.workplace,
    this.consultationPriceUzs,
    this.consultationSpecialties = const <String>[],
    this.ratingAverage,
    this.ratingCount = 0,
    this.answeredCount = 0,
    this.patientCount = 0,
    this.subscription,
  });

  factory DoctorProfile.fromJson(Map<String, dynamic> json) => DoctorProfile(
        id: '${json['id']}',
        userId: '${json['user_id']}',
        fullName: '${json['full_name']}',
        specialty: '${json['specialty']}',
        experienceYears: _asInt(json['experience_years']),
        verificationStatus: '${json['verification_status']}',
        connectCode: '${json['connect_code']}',
        consultationOpen: _asBool(json['consultation_open']),
        age: json['age'] == null ? null : _asInt(json['age']),
        bio: json['bio'] as String?,
        workplace: json['workplace'] as String?,
        consultationPriceUzs: json['consultation_price_uzs'] == null
            ? null
            : _asInt(json['consultation_price_uzs']),
        consultationSpecialties: _asStringList(json['consultation_specialties']),
        ratingAverage: _asDouble(json['rating_average']),
        ratingCount: _asInt(json['rating_count']),
        answeredCount: _asInt(json['answered_count']),
        patientCount: _asInt(json['patient_count']),
        subscription: json['subscription'] == null
            ? null
            : SubscriptionInfo.fromJson(_asMap(json['subscription'])),
      );

  final String id;
  final String userId;
  final String fullName;
  final String specialty;
  final int experienceYears;
  final String verificationStatus;
  final String connectCode;
  final bool consultationOpen;
  final int? age;
  final String? bio;
  final String? workplace;
  final int? consultationPriceUzs;
  final List<String> consultationSpecialties;
  final double? ratingAverage;
  final int ratingCount;
  final int answeredCount;
  final int patientCount;
  final SubscriptionInfo? subscription;

  bool get isApproved => verificationStatus == 'approved';
  bool get isPending => verificationStatus == 'pending';
}

class SubscriptionInfo {
  const SubscriptionInfo({
    required this.plan,
    required this.status,
    required this.isActive,
    this.currentPeriodEnd,
  });

  factory SubscriptionInfo.fromJson(Map<String, dynamic> json) => SubscriptionInfo(
        plan: '${json['plan']}',
        status: '${json['status']}',
        isActive: _asBool(json['is_active']),
        currentPeriodEnd: _asDate(json['current_period_end']),
      );

  final String plan;
  final String status;
  final bool isActive;
  final DateTime? currentPeriodEnd;
}

class SpecialtyOption {
  const SpecialtyOption({
    required this.code,
    required this.name,
    required this.recommendedPriceUzs,
  });

  factory SpecialtyOption.fromJson(Map<String, dynamic> json) => SpecialtyOption(
        code: '${json['code']}',
        name: _asMap(json['name']),
        recommendedPriceUzs: _asInt(json['recommended_price_uzs']),
      );

  final String code;
  final Map<String, dynamic> name;
  final int recommendedPriceUzs;
}

class DoctorSearchItem {
  const DoctorSearchItem({
    required this.userId,
    required this.fullName,
    required this.specialty,
    required this.experienceYears,
    required this.consultationPriceUzs,
    this.ratingAverage,
    this.ratingCount = 0,
    this.avatarUrl,
    this.isConnected = false,
  });

  factory DoctorSearchItem.fromJson(Map<String, dynamic> json) => DoctorSearchItem(
        userId: '${json['user_id']}',
        fullName: '${json['full_name']}',
        specialty: '${json['specialty']}',
        experienceYears: _asInt(json['experience_years']),
        consultationPriceUzs: _asInt(json['consultation_price_uzs']),
        ratingAverage: _asDouble(json['rating_average']),
        ratingCount: _asInt(json['rating_count']),
        avatarUrl: json['avatar_url'] as String?,
        isConnected: _asBool(json['is_connected']),
      );

  final String userId;
  final String fullName;
  final String specialty;
  final int experienceYears;
  final int consultationPriceUzs;
  final double? ratingAverage;
  final int ratingCount;
  final String? avatarUrl;
  final bool isConnected;
}

// ------------------------------------------------------------ care thread
class CareThread {
  const CareThread({
    required this.id,
    required this.kind,
    required this.patientUserId,
    this.doctorUserId,
    this.title,
    this.doctorName,
    this.doctorSpecialty,
    this.doctorRating,
    this.patientName,
    this.primaryDiagnosis,
    this.diagnosisStatus,
    this.lastActivityAt,
    this.connectedAt,
  });

  factory CareThread.fromJson(Map<String, dynamic> json) => CareThread(
        id: '${json['id']}',
        kind: '${json['kind']}',
        patientUserId: '${json['patient_user_id']}',
        doctorUserId: json['doctor_user_id'] as String?,
        title: json['title'] as String?,
        doctorName: json['doctor_name'] as String?,
        doctorSpecialty: json['doctor_specialty'] as String?,
        doctorRating: _asDouble(json['doctor_rating']),
        patientName: json['patient_name'] as String?,
        primaryDiagnosis: json['primary_diagnosis'] as String?,
        diagnosisStatus: json['diagnosis_status'] as String?,
        lastActivityAt: _asDate(json['last_activity_at']),
        connectedAt: _asDate(json['connected_at']),
      );

  final String id;
  final String kind;
  final String patientUserId;
  final String? doctorUserId;
  final String? title;
  final String? doctorName;
  final String? doctorSpecialty;
  final double? doctorRating;
  final String? patientName;
  final String? primaryDiagnosis;
  final String? diagnosisStatus;
  final DateTime? lastActivityAt;
  final DateTime? connectedAt;

  /// The patient's private container, not shared with any doctor.
  bool get isPersonal => kind == 'personal';

  String get displayName => doctorName ?? title ?? '';
}

class PatientListItem {
  const PatientListItem({
    required this.careThreadId,
    required this.fullName,
    this.patientUserId,
    this.phone,
    this.primaryDiagnosis,
    this.diagnosisStatus,
    this.lastActivityAt,
    this.riskLevel = 'green',
    this.riskReasons = const <String>[],
    this.isPendingInvite = false,
    this.pendingInviteCode,
    this.openEscalations = 0,
  });

  factory PatientListItem.fromJson(Map<String, dynamic> json) => PatientListItem(
        careThreadId: '${json['care_thread_id']}',
        fullName: '${json['full_name']}',
        patientUserId: json['patient_user_id'] as String?,
        phone: json['phone'] as String?,
        primaryDiagnosis: json['primary_diagnosis'] as String?,
        diagnosisStatus: json['diagnosis_status'] as String?,
        lastActivityAt: _asDate(json['last_activity_at']),
        riskLevel: (json['risk_level'] as String?) ?? 'green',
        riskReasons: _asStringList(json['risk_reasons']),
        isPendingInvite: _asBool(json['is_pending_invite']),
        pendingInviteCode: json['pending_invite_code'] as String?,
        openEscalations: _asInt(json['open_escalations']),
      );

  final String careThreadId;
  final String fullName;
  final String? patientUserId;
  final String? phone;
  final String? primaryDiagnosis;
  final String? diagnosisStatus;
  final DateTime? lastActivityAt;
  final String riskLevel;
  final List<String> riskReasons;
  final bool isPendingInvite;
  final String? pendingInviteCode;
  final int openEscalations;
}

class PatientInvite {
  const PatientInvite({
    required this.id,
    required this.code,
    required this.fullName,
    required this.phone,
    required this.status,
    this.diagnosisText,
    this.templateName,
    this.shareText,
    this.expiresAt,
  });

  factory PatientInvite.fromJson(Map<String, dynamic> json) => PatientInvite(
        id: '${json['id']}',
        code: '${json['code']}',
        fullName: '${json['full_name']}',
        phone: '${json['phone']}',
        status: '${json['status']}',
        diagnosisText: json['diagnosis_text'] as String?,
        templateName: json['template_name'] as String?,
        shareText: json['share_text'] as String?,
        expiresAt: _asDate(json['expires_at']),
      );

  final String id;
  final String code;
  final String fullName;
  final String phone;
  final String status;
  final String? diagnosisText;
  final String? templateName;
  final String? shareText;
  final DateTime? expiresAt;
}

class Diagnosis {
  const Diagnosis({
    required this.id,
    required this.careThreadId,
    required this.text,
    required this.status,
    this.templateId,
    this.templateName,
    this.notes,
    this.isActive = true,
    this.verifiedAt,
    this.pendingChangeRequest,
  });

  factory Diagnosis.fromJson(Map<String, dynamic> json) => Diagnosis(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        text: '${json['text']}',
        status: '${json['status']}',
        templateId: json['template_id'] as String?,
        templateName: json['template_name'] as String?,
        notes: json['notes'] as String?,
        isActive: _asBool(json['is_active'], true),
        verifiedAt: _asDate(json['verified_at']),
        pendingChangeRequest: json['pending_change_request'] == null
            ? null
            : ChangeRequest.fromJson(_asMap(json['pending_change_request'])),
      );

  final String id;
  final String careThreadId;
  final String text;
  final String status;
  final String? templateId;
  final String? templateName;
  final String? notes;
  final bool isActive;
  final DateTime? verifiedAt;
  final ChangeRequest? pendingChangeRequest;

  /// A verified diagnosis is read-only for the patient (spec 2.3).
  bool get isVerified => status == 'verified';
}

class ChangeRequest {
  const ChangeRequest({
    required this.id,
    required this.diagnosisId,
    required this.comment,
    required this.status,
    this.proposedText,
    this.resolutionNote,
  });

  factory ChangeRequest.fromJson(Map<String, dynamic> json) => ChangeRequest(
        id: '${json['id']}',
        diagnosisId: '${json['diagnosis_id']}',
        comment: '${json['comment']}',
        status: '${json['status']}',
        proposedText: json['proposed_text'] as String?,
        resolutionNote: json['resolution_note'] as String?,
      );

  final String id;
  final String diagnosisId;
  final String comment;
  final String status;
  final String? proposedText;
  final String? resolutionNote;

  bool get isPending => status == 'pending';
}

class DiagnosisTemplate {
  const DiagnosisTemplate({
    required this.id,
    required this.code,
    required this.name,
    this.specialty,
  });

  factory DiagnosisTemplate.fromJson(Map<String, dynamic> json) => DiagnosisTemplate(
        id: '${json['id']}',
        code: '${json['code']}',
        name: _asMap(json['name']),
        specialty: json['specialty'] as String?,
      );

  final String id;
  final String code;
  final Map<String, dynamic> name;
  final String? specialty;
}

class TemplateMatch {
  const TemplateMatch({
    required this.confidence,
    this.templateId,
    this.templateName,
    this.alternatives = const <DiagnosisTemplate>[],
  });

  factory TemplateMatch.fromJson(Map<String, dynamic> json) => TemplateMatch(
        confidence: _asDouble(json['confidence']) ?? 0,
        templateId: json['template_id'] as String?,
        templateName: json['template_name'] as String?,
        alternatives: _asMapList(json['alternatives'])
            .map((Map<String, dynamic> e) => DiagnosisTemplate(
                  id: '${e['id']}',
                  code: '${e['code']}',
                  name: <String, dynamic>{'uz': e['name']},
                  specialty: e['specialty'] as String?,
                ))
            .toList(),
      );

  final double confidence;
  final String? templateId;
  final String? templateName;
  final List<DiagnosisTemplate> alternatives;
}

class Medication {
  const Medication({
    required this.id,
    required this.careThreadId,
    required this.name,
    required this.dose,
    required this.times,
    this.instructions,
    this.weekdays = const <int>[],
    this.isActive = true,
    this.adherence7d,
  });

  factory Medication.fromJson(Map<String, dynamic> json) => Medication(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        name: '${json['name']}',
        dose: '${json['dose']}',
        times: _asStringList(json['times']),
        instructions: json['instructions'] as String?,
        weekdays: (json['weekdays'] as List<dynamic>? ?? <dynamic>[])
            .map((Object? e) => _asInt(e))
            .toList(),
        isActive: _asBool(json['is_active'], true),
        adherence7d: _asDouble(json['adherence_7d']),
      );

  final String id;
  final String careThreadId;
  final String name;
  final String dose;
  final List<String> times;
  final String? instructions;
  final List<int> weekdays;
  final bool isActive;
  final double? adherence7d;
}

class MedicationDose {
  const MedicationDose({
    required this.id,
    required this.medicationId,
    required this.careThreadId,
    required this.scheduledAt,
    required this.status,
    this.medicationName,
    this.doseText,
    this.takenAt,
    this.confirmedVia,
  });

  factory MedicationDose.fromJson(Map<String, dynamic> json) => MedicationDose(
        id: '${json['id']}',
        medicationId: '${json['medication_id']}',
        careThreadId: '${json['care_thread_id']}',
        scheduledAt: _asDate(json['scheduled_at']) ?? DateTime.now(),
        status: '${json['status']}',
        medicationName: json['medication_name'] as String?,
        doseText: json['dose_text'] as String?,
        takenAt: _asDate(json['taken_at']),
        confirmedVia: json['confirmed_via'] as String?,
      );

  final String id;
  final String medicationId;
  final String careThreadId;
  final DateTime scheduledAt;
  final String status;
  final String? medicationName;
  final String? doseText;
  final DateTime? takenAt;
  final String? confirmedVia;

  bool get isTaken => status == 'taken';
  bool get isPending => status == 'pending';
  bool get isMissed => status == 'missed';

  /// True when the intake was confirmed by pressing 1 on an automated call.
  bool get confirmedByCall => confirmedVia == 'ivr';
}

class MetricSeries {
  const MetricSeries({
    required this.id,
    required this.careThreadId,
    required this.key,
    required this.label,
    required this.unit,
    this.valueType = 'number',
    this.targetMin,
    this.targetMax,
    this.criticalMin,
    this.criticalMax,
    this.decimals = 1,
    this.chartType = 'line',
    this.latestValue,
    this.latestRecordedAt,
  });

  factory MetricSeries.fromJson(Map<String, dynamic> json) => MetricSeries(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        key: '${json['key']}',
        label: _asMap(json['label']),
        unit: '${json['unit']}',
        valueType: (json['value_type'] as String?) ?? 'number',
        targetMin: _asDouble(json['target_min']),
        targetMax: _asDouble(json['target_max']),
        criticalMin: _asDouble(json['critical_min']),
        criticalMax: _asDouble(json['critical_max']),
        decimals: _asInt(json['decimals'], 1),
        chartType: (json['chart_type'] as String?) ?? 'line',
        latestValue: _asDouble(json['latest_value']),
        latestRecordedAt: _asDate(json['latest_recorded_at']),
      );

  final String id;
  final String careThreadId;
  final String key;
  final Map<String, dynamic> label;
  final String unit;
  final String valueType;
  final double? targetMin;
  final double? targetMax;
  final double? criticalMin;
  final double? criticalMax;
  final int decimals;
  final String chartType;
  final double? latestValue;
  final DateTime? latestRecordedAt;

  /// Paired indicator such as blood pressure (systolic/diastolic).
  bool get isPair => valueType == 'pair';

  bool isOutOfRange(double value) {
    if (targetMin != null && value < targetMin!) return true;
    if (targetMax != null && value > targetMax!) return true;
    return false;
  }

  bool isCritical(double value) {
    if (criticalMin != null && value < criticalMin!) return true;
    if (criticalMax != null && value > criticalMax!) return true;
    return false;
  }
}

class TrendPoint {
  const TrendPoint({required this.at, required this.value, this.valueSecondary});

  factory TrendPoint.fromJson(Map<String, dynamic> json) => TrendPoint(
        at: _asDate(json['at']) ?? DateTime.now(),
        value: _asDouble(json['value']) ?? 0,
        valueSecondary: _asDouble(json['value_secondary']),
      );

  final DateTime at;
  final double value;
  final double? valueSecondary;
}

class TrendData {
  const TrendData({
    required this.series,
    required this.points,
    this.average,
    this.minimum,
    this.maximum,
    this.inTargetPercent,
  });

  factory TrendData.fromJson(Map<String, dynamic> json) => TrendData(
        series: MetricSeries.fromJson(_asMap(json['series'])),
        points: _asMapList(json['points']).map(TrendPoint.fromJson).toList(),
        average: _asDouble(json['average']),
        minimum: _asDouble(json['minimum']),
        maximum: _asDouble(json['maximum']),
        inTargetPercent: _asDouble(json['in_target_percent']),
      );

  final MetricSeries series;
  final List<TrendPoint> points;
  final double? average;
  final double? minimum;
  final double? maximum;
  final double? inTargetPercent;
}

class CheckinQuestion {
  const CheckinQuestion({
    required this.key,
    required this.prompt,
    required this.type,
    this.unit,
    this.metricKey,
    this.options = const <Map<String, dynamic>>[],
    this.required = true,
  });

  factory CheckinQuestion.fromJson(Map<String, dynamic> json) => CheckinQuestion(
        key: '${json['key']}',
        prompt: _asMap(json['prompt']),
        type: '${json['type']}',
        unit: json['unit'] as String?,
        metricKey: json['metric_key'] as String?,
        options: _asMapList(json['options']),
        required: _asBool(json['required'], true),
      );

  final String key;
  final Map<String, dynamic> prompt;
  final String type;
  final String? unit;
  final String? metricKey;
  final List<Map<String, dynamic>> options;
  // ignore: avoid_field_initializers_in_const_classes
  final bool required;
}

class TodayData {
  const TodayData({
    required this.careThreadId,
    required this.questions,
    required this.doses,
    required this.alreadySubmitted,
    this.submittedAnswers = const <String, dynamic>{},
  });

  factory TodayData.fromJson(Map<String, dynamic> json) => TodayData(
        careThreadId: '${json['care_thread_id']}',
        questions: _asMapList(json['questions']).map(CheckinQuestion.fromJson).toList(),
        doses: _asMapList(json['doses']).map(MedicationDose.fromJson).toList(),
        alreadySubmitted: _asBool(json['already_submitted']),
        submittedAnswers: _asMap(json['submitted_answers']),
      );

  final String careThreadId;
  final List<CheckinQuestion> questions;
  final List<MedicationDose> doses;
  final bool alreadySubmitted;
  final Map<String, dynamic> submittedAnswers;
}

class ThreadDocument {
  const ThreadDocument({
    required this.id,
    required this.filename,
    required this.contentType,
    required this.sizeBytes,
    this.downloadUrl,
  });

  factory ThreadDocument.fromJson(Map<String, dynamic> json) => ThreadDocument(
        id: '${json['id']}',
        filename: '${json['filename']}',
        contentType: '${json['content_type']}',
        sizeBytes: _asInt(json['size_bytes']),
        downloadUrl: json['download_url'] as String?,
      );

  final String id;
  final String filename;
  final String contentType;
  final int sizeBytes;
  final String? downloadUrl;

  bool get isPdf => contentType == 'application/pdf';
}

// ---------------------------------------------------------- consultations
class Consultation {
  const Consultation({
    required this.id,
    required this.status,
    required this.targeting,
    required this.specialty,
    required this.question,
    required this.priceUzs,
    required this.patientUserId,
    this.doctorUserId,
    this.doctorName,
    this.doctorSpecialty,
    this.doctorRating,
    this.patientName,
    this.answerText,
    this.rating,
    this.review,
    this.createdAt,
    this.slaExpiresAt,
    this.answeredAt,
    this.refundedAt,
    this.snapshot,
  });

  factory Consultation.fromJson(Map<String, dynamic> json) => Consultation(
        id: '${json['id']}',
        status: '${json['status']}',
        targeting: '${json['targeting']}',
        specialty: '${json['specialty']}',
        question: '${json['question']}',
        priceUzs: _asInt(json['price_uzs']),
        patientUserId: '${json['patient_user_id']}',
        doctorUserId: json['doctor_user_id'] as String?,
        doctorName: json['doctor_name'] as String?,
        doctorSpecialty: json['doctor_specialty'] as String?,
        doctorRating: _asDouble(json['doctor_rating']),
        patientName: json['patient_name'] as String?,
        answerText: json['answer_text'] as String?,
        rating: json['rating'] == null ? null : _asInt(json['rating']),
        review: json['review'] as String?,
        createdAt: _asDate(json['created_at']),
        slaExpiresAt: _asDate(json['sla_expires_at']),
        answeredAt: _asDate(json['answered_at']),
        refundedAt: _asDate(json['refunded_at']),
        snapshot: json['snapshot'] == null
            ? null
            : ConsultationSnapshot.fromJson(_asMap(json['snapshot'])),
      );

  final String id;
  final String status;
  final String targeting;
  final String specialty;
  final String question;
  final int priceUzs;
  final String patientUserId;
  final String? doctorUserId;
  final String? doctorName;
  final String? doctorSpecialty;
  final double? doctorRating;
  final String? patientName;
  final String? answerText;
  final int? rating;
  final String? review;
  final DateTime? createdAt;
  final DateTime? slaExpiresAt;
  final DateTime? answeredAt;
  final DateTime? refundedAt;
  final ConsultationSnapshot? snapshot;

  bool get isWaiting => status == 'open' || status == 'claimed';
  bool get isAnswered => status == 'answered' || status == 'rated';
  bool get isRated => status == 'rated';
  bool get isRefunded => status == 'refunded';
}

class ConsultationSnapshot {
  const ConsultationSnapshot({
    this.diagnoses = const <Map<String, dynamic>>[],
    this.medications = const <Map<String, dynamic>>[],
    this.recentReadings = const <Map<String, dynamic>>[],
    this.patientAge,
    this.patientGender,
    this.shared = true,
  });

  factory ConsultationSnapshot.fromJson(Map<String, dynamic> json) =>
      ConsultationSnapshot(
        diagnoses: _asMapList(json['diagnoses']),
        medications: _asMapList(json['medications']),
        recentReadings: _asMapList(json['recent_readings']),
        patientAge: json['patient_age'] == null ? null : _asInt(json['patient_age']),
        patientGender: json['patient_gender'] as String?,
        shared: _asBool(json['shared'], true),
      );

  final List<Map<String, dynamic>> diagnoses;
  final List<Map<String, dynamic>> medications;
  final List<Map<String, dynamic>> recentReadings;
  final int? patientAge;
  final String? patientGender;
  final bool shared;

  bool get isEmpty => diagnoses.isEmpty && medications.isEmpty && recentReadings.isEmpty;
}

class ConsultationListItem {
  const ConsultationListItem({
    required this.id,
    required this.status,
    required this.specialty,
    required this.displayName,
    required this.questionPreview,
    required this.priceUzs,
    this.createdAt,
    this.slaExpiresAt,
    this.rating,
    this.answeredAt,
  });

  factory ConsultationListItem.fromJson(Map<String, dynamic> json) =>
      ConsultationListItem(
        id: '${json['id']}',
        status: '${json['status']}',
        specialty: '${json['specialty']}',
        displayName: '${json['display_name']}',
        questionPreview: '${json['question_preview']}',
        priceUzs: _asInt(json['price_uzs']),
        createdAt: _asDate(json['created_at']),
        slaExpiresAt: _asDate(json['sla_expires_at']),
        rating: json['rating'] == null ? null : _asInt(json['rating']),
        answeredAt: _asDate(json['answered_at']),
      );

  final String id;
  final String status;
  final String specialty;
  final String displayName;
  final String questionPreview;
  final int priceUzs;
  final DateTime? createdAt;
  final DateTime? slaExpiresAt;
  final int? rating;
  final DateTime? answeredAt;

  bool get isClaimable => status == 'open';
}

class PriceQuote {
  const PriceQuote({
    required this.specialty,
    required this.priceUzs,
    required this.slaHours,
    this.isDoctorCustom = false,
  });

  factory PriceQuote.fromJson(Map<String, dynamic> json) => PriceQuote(
        specialty: '${json['specialty']}',
        priceUzs: _asInt(json['price_uzs']),
        slaHours: _asInt(json['sla_hours'], 24),
        isDoctorCustom: _asBool(json['is_doctor_custom']),
      );

  final String specialty;
  final int priceUzs;
  final int slaHours;
  final bool isDoctorCustom;
}

class CheckoutInfo {
  const CheckoutInfo({
    required this.paymentId,
    required this.checkoutUrl,
    required this.amountUzs,
  });

  factory CheckoutInfo.fromJson(Map<String, dynamic> json) => CheckoutInfo(
        paymentId: '${json['payment_id']}',
        checkoutUrl: '${json['checkout_url']}',
        amountUzs: _asInt(json['amount_uzs']),
      );

  final String paymentId;
  final String checkoutUrl;
  final int amountUzs;
}

// -------------------------------------------------------------------- ai
class AiMessage {
  const AiMessage({
    required this.id,
    required this.careThreadId,
    required this.role,
    required this.content,
    this.outcome,
    this.citations = const <Map<String, dynamic>>[],
    this.createdAt,
  });

  factory AiMessage.fromJson(Map<String, dynamic> json) => AiMessage(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        role: '${json['role']}',
        content: '${json['content']}',
        outcome: json['outcome'] as String?,
        citations: _asMapList(json['citations']),
        createdAt: _asDate(json['created_at']),
      );

  final String id;
  final String careThreadId;
  final String role;
  final String content;
  final String? outcome;
  final List<Map<String, dynamic>> citations;
  final DateTime? createdAt;

  bool get isFromPatient => role == 'patient';
  bool get isFromDoctor => role == 'doctor';
  bool get isEmergency => outcome == 'emergency';
  bool get wasEscalated => outcome == 'escalated';
}

class AiReply {
  const AiReply({
    required this.message,
    required this.outcome,
    this.citations = const <Map<String, dynamic>>[],
    this.escalatedToDoctor,
    this.suggestPaidConsultation = false,
  });

  factory AiReply.fromJson(Map<String, dynamic> json) => AiReply(
        message: AiMessage.fromJson(_asMap(json['message'])),
        outcome: '${json['outcome']}',
        citations: _asMapList(json['citations']),
        escalatedToDoctor: json['escalated_to_doctor'] as String?,
        suggestPaidConsultation: _asBool(json['suggest_paid_consultation']),
      );

  final AiMessage message;
  final String outcome;
  final List<Map<String, dynamic>> citations;
  final String? escalatedToDoctor;
  final bool suggestPaidConsultation;
}

class Escalation {
  const Escalation({
    required this.id,
    required this.careThreadId,
    required this.question,
    required this.reason,
    required this.isOpen,
    this.patientName,
    this.aiNote,
    this.answerText,
    this.createdAt,
  });

  factory Escalation.fromJson(Map<String, dynamic> json) => Escalation(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        question: '${json['question']}',
        reason: '${json['reason']}',
        isOpen: _asBool(json['is_open'], true),
        patientName: json['patient_name'] as String?,
        aiNote: json['ai_note'] as String?,
        answerText: json['answer_text'] as String?,
        createdAt: _asDate(json['created_at']),
      );

  final String id;
  final String careThreadId;
  final String question;
  final String reason;
  final bool isOpen;
  final String? patientName;
  final String? aiNote;
  final String? answerText;
  final DateTime? createdAt;
}

class WeeklyReport {
  const WeeklyReport({
    required this.id,
    required this.careThreadId,
    required this.summaryText,
    this.periodStart,
    this.periodEnd,
    this.payload = const <String, dynamic>{},
  });

  factory WeeklyReport.fromJson(Map<String, dynamic> json) => WeeklyReport(
        id: '${json['id']}',
        careThreadId: '${json['care_thread_id']}',
        summaryText: '${json['summary_text']}',
        periodStart: _asDate(json['period_start']),
        periodEnd: _asDate(json['period_end']),
        payload: _asMap(json['payload']),
      );

  final String id;
  final String careThreadId;
  final String summaryText;
  final DateTime? periodStart;
  final DateTime? periodEnd;
  final Map<String, dynamic> payload;
}

class AppNotification {
  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    this.data = const <String, dynamic>{},
    this.readAt,
    this.createdAt,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) => AppNotification(
        id: '${json['id']}',
        type: '${json['type']}',
        title: '${json['title']}',
        body: '${json['body']}',
        data: _asMap(json['data']),
        readAt: _asDate(json['read_at']),
        createdAt: _asDate(json['created_at']),
      );

  final String id;
  final String type;
  final String title;
  final String body;
  final Map<String, dynamic> data;
  final DateTime? readAt;
  final DateTime? createdAt;

  bool get isUnread => readAt == null;
}

// --------------------------------------------------------------- billing
class Wallet {
  const Wallet({
    required this.balanceUzs,
    required this.minPayoutUzs,
    required this.canRequestPayout,
    this.lifetimeEarnedUzs = 0,
    this.lifetimePaidOutUzs = 0,
  });

  factory Wallet.fromJson(Map<String, dynamic> json) => Wallet(
        balanceUzs: _asInt(json['balance_uzs']),
        minPayoutUzs: _asInt(json['min_payout_uzs']),
        canRequestPayout: _asBool(json['can_request_payout']),
        lifetimeEarnedUzs: _asInt(json['lifetime_earned_uzs']),
        lifetimePaidOutUzs: _asInt(json['lifetime_paid_out_uzs']),
      );

  final int balanceUzs;
  final int minPayoutUzs;
  final bool canRequestPayout;
  final int lifetimeEarnedUzs;
  final int lifetimePaidOutUzs;
}

class WalletTransaction {
  const WalletTransaction({
    required this.id,
    required this.type,
    required this.amountUzs,
    required this.balanceAfterUzs,
    this.description,
    this.counterpartyName,
    this.createdAt,
  });

  factory WalletTransaction.fromJson(Map<String, dynamic> json) => WalletTransaction(
        id: '${json['id']}',
        type: '${json['type']}',
        amountUzs: _asInt(json['amount_uzs']),
        balanceAfterUzs: _asInt(json['balance_after_uzs']),
        description: json['description'] as String?,
        counterpartyName: json['counterparty_name'] as String?,
        createdAt: _asDate(json['created_at']),
      );

  final String id;
  final String type;
  final int amountUzs;
  final int balanceAfterUzs;
  final String? description;
  final String? counterpartyName;
  final DateTime? createdAt;

  bool get isCredit => amountUzs > 0;
}

class PayoutRequest {
  const PayoutRequest({
    required this.id,
    required this.amountUzs,
    required this.status,
    this.cardLast4,
    this.createdAt,
  });

  factory PayoutRequest.fromJson(Map<String, dynamic> json) => PayoutRequest(
        id: '${json['id']}',
        amountUzs: _asInt(json['amount_uzs']),
        status: '${json['status']}',
        cardLast4: json['card_last4'] as String?,
        createdAt: _asDate(json['created_at']),
      );

  final String id;
  final int amountUzs;
  final String status;
  final String? cardLast4;
  final DateTime? createdAt;
}

class SubscriptionStatus {
  const SubscriptionStatus({
    required this.status,
    required this.isActive,
    required this.monthlyPriceUzs,
    required this.yearlyPriceUzs,
    this.plan,
    this.currentPeriodEnd,
  });

  factory SubscriptionStatus.fromJson(Map<String, dynamic> json) => SubscriptionStatus(
        status: '${json['status']}',
        isActive: _asBool(json['is_active']),
        monthlyPriceUzs: _asInt(json['monthly_price_uzs']),
        yearlyPriceUzs: _asInt(json['yearly_price_uzs']),
        plan: json['plan'] as String?,
        currentPeriodEnd: _asDate(json['current_period_end']),
      );

  final String status;
  final bool isActive;
  final int monthlyPriceUzs;
  final int yearlyPriceUzs;
  final String? plan;
  final DateTime? currentPeriodEnd;
}

/// A page of results from a paginated endpoint.
class Paged<T> {
  const Paged({
    required this.items,
    required this.total,
    required this.limit,
    required this.offset,
  });

  factory Paged.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) parse,
  ) =>
      Paged<T>(
        items: _asMapList(json['items']).map(parse).toList(),
        total: _asInt(json['total']),
        limit: _asInt(json['limit'], 20),
        offset: _asInt(json['offset']),
      );

  final List<T> items;
  final int total;
  final int limit;
  final int offset;

  bool get hasMore => offset + items.length < total;
}
