import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/models.dart';
import '../data/repositories/repositories.dart';
import 'network/api_client.dart';
import 'network/token_storage.dart';

/// Dependency wiring. Providers are declared by hand (no `riverpod_generator`)
/// so the project builds without a code-generation step.

final Provider<TokenStorage> tokenStorageProvider =
    Provider<TokenStorage>((Ref ref) => TokenStorage());

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((Ref ref) {
  final ApiClient client = ApiClient(storage: ref.watch(tokenStorageProvider));
  // A session that cannot be refreshed drops the app back to sign-in.
  client.onAuthFailure = () => ref.read(sessionProvider.notifier).forceSignOut();
  return client;
});

final Provider<AuthRepository> authRepositoryProvider =
    Provider<AuthRepository>((Ref ref) => AuthRepository(ref.watch(apiClientProvider)));

final Provider<DoctorRepository> doctorRepositoryProvider = Provider<DoctorRepository>(
    (Ref ref) => DoctorRepository(ref.watch(apiClientProvider)));

final Provider<PatientRepository> patientRepositoryProvider = Provider<PatientRepository>(
    (Ref ref) => PatientRepository(ref.watch(apiClientProvider)));

final Provider<ThreadRepository> threadRepositoryProvider = Provider<ThreadRepository>(
    (Ref ref) => ThreadRepository(ref.watch(apiClientProvider)));

final Provider<ConsultationRepository> consultationRepositoryProvider =
    Provider<ConsultationRepository>(
        (Ref ref) => ConsultationRepository(ref.watch(apiClientProvider)));

final Provider<AiRepository> aiRepositoryProvider =
    Provider<AiRepository>((Ref ref) => AiRepository(ref.watch(apiClientProvider)));

final Provider<NotificationRepository> notificationRepositoryProvider =
    Provider<NotificationRepository>(
        (Ref ref) => NotificationRepository(ref.watch(apiClientProvider)));

final Provider<BillingRepository> billingRepositoryProvider = Provider<BillingRepository>(
    (Ref ref) => BillingRepository(ref.watch(apiClientProvider)));

// ------------------------------------------------------------------ locale
class LocaleController extends StateNotifier<Locale> {
  LocaleController(this._storage) : super(const Locale('uz')) {
    _restore();
  }

  final TokenStorage _storage;

  Future<void> _restore() async {
    final String? saved = await _storage.readLocale();
    if (saved != null) state = Locale(saved);
  }

  Future<void> set(String code) async {
    state = Locale(code);
    await _storage.saveLocale(code);
  }
}

final StateNotifierProvider<LocaleController, Locale> localeProvider =
    StateNotifierProvider<LocaleController, Locale>(
  (Ref ref) => LocaleController(ref.watch(tokenStorageProvider)),
);

// ----------------------------------------------------------------- session
/// Where the app is in the onboarding sequence.
enum SessionStage {
  /// Still restoring a stored session.
  loading,

  /// No session at all — show the welcome screen.
  signedOut,

  /// Provider sign-in succeeded but the phone is not verified (spec 3).
  /// This screen has no skip button.
  needsPhone,

  /// Signed in, but the role has not been chosen yet.
  needsRole,

  /// Role chosen, profile form not completed.
  needsProfile,

  /// Fully onboarded.
  ready,
}

class SessionState {
  const SessionState({
    required this.stage,
    this.user,
    this.authState,
    this.onboardingToken,
    this.error,
  });

  const SessionState.loading() : this(stage: SessionStage.loading);
  const SessionState.signedOut() : this(stage: SessionStage.signedOut);

  final SessionStage stage;
  final AppUser? user;
  final AuthState? authState;

  /// Short-lived token that only authorises phone verification.
  final String? onboardingToken;
  final String? error;

  bool get isDoctor => authState?.isDoctor ?? user?.role == 'doctor';
  bool get isPatient => authState?.isPatient ?? user?.role == 'patient';

  SessionState copyWith({
    SessionStage? stage,
    AppUser? user,
    AuthState? authState,
    String? onboardingToken,
    String? error,
  }) =>
      SessionState(
        stage: stage ?? this.stage,
        user: user ?? this.user,
        authState: authState ?? this.authState,
        onboardingToken: onboardingToken ?? this.onboardingToken,
        error: error,
      );
}

class SessionController extends StateNotifier<SessionState> {
  SessionController(this._ref) : super(const SessionState.loading()) {
    restore();
  }

  final Ref _ref;

  AuthRepository get _auth => _ref.read(authRepositoryProvider);
  TokenStorage get _storage => _ref.read(tokenStorageProvider);

  /// Load any stored session on launch.
  Future<void> restore() async {
    if (!await _storage.hasSession) {
      state = const SessionState.signedOut();
      return;
    }
    try {
      final AppUser user = await _auth.me();
      final AuthState authState = await _auth.state();
      _applyLocale(user.locale);
      state = SessionState(
        stage: _stageFor(authState),
        user: user,
        authState: authState,
      );
    } catch (_) {
      await _storage.clear();
      state = const SessionState.signedOut();
    }
  }

  /// Apply the outcome of a sign-in call.
  Future<void> applySession(SessionResponse response) async {
    if (response.hasSession) {
      await _storage.saveTokens(
        accessToken: response.accessToken!,
        refreshToken: response.refreshToken!,
      );
      if (response.user != null) _applyLocale(response.user!.locale);
      state = SessionState(
        stage: _stageFor(response.state),
        user: response.user,
        authState: response.state,
      );
      return;
    }

    // No tokens: the phone gate must be satisfied first.
    state = SessionState(
      stage: SessionStage.needsPhone,
      authState: response.state,
      onboardingToken: response.onboardingToken,
    );
  }

  /// Re-read the onboarding state after finishing a step.
  Future<void> refresh() async {
    try {
      final AppUser user = await _auth.me();
      final AuthState authState = await _auth.state();
      state = SessionState(
        stage: _stageFor(authState),
        user: user,
        authState: authState,
      );
    } catch (_) {
      // Keep the current stage; a transient failure should not sign the user out.
    }
  }

  Future<void> selectRole(String role) async {
    final SessionResponse response = await _auth.selectRole(role);
    state = SessionState(
      stage: _stageFor(response.state),
      user: response.user ?? state.user,
      authState: response.state,
    );
  }

  Future<void> updateUser(Map<String, dynamic> changes) async {
    final AppUser user = await _auth.updateMe(changes);
    if (changes.containsKey('locale')) _applyLocale(user.locale);
    state = state.copyWith(user: user);
  }

  Future<void> signOut() async {
    try {
      final String? refreshToken = await _storage.readRefreshToken();
      await _auth.logout(refreshToken: refreshToken);
    } catch (_) {
      // Signing out locally matters more than telling the server about it.
    }
    await _storage.clear();
    state = const SessionState.signedOut();
  }

  /// Called by the API client when the session cannot be refreshed.
  void forceSignOut() {
    state = const SessionState.signedOut();
  }

  void _applyLocale(String code) {
    _ref.read(localeProvider.notifier).set(code);
  }

  SessionStage _stageFor(AuthState authState) {
    if (authState.phoneVerificationRequired) return SessionStage.needsPhone;
    if (authState.roleSelectionRequired) return SessionStage.needsRole;
    if (authState.profileSetupRequired) return SessionStage.needsProfile;
    return SessionStage.ready;
  }
}

final StateNotifierProvider<SessionController, SessionState> sessionProvider =
    StateNotifierProvider<SessionController, SessionState>(
  SessionController.new,
);

// ------------------------------------------------------------------- data
final FutureProvider<List<CareThread>> threadsProvider =
    FutureProvider<List<CareThread>>((Ref ref) async {
  return ref.watch(threadRepositoryProvider).list();
});

/// Which doctor's thread the patient is currently looking at.
///
/// The switcher on the "Bugun" tab writes here, and every clinical query reads
/// it — the app never mixes two doctors' data on one screen (spec 2.2).
final StateProvider<String?> activeThreadIdProvider =
    StateProvider<String?>((Ref ref) => null);

final FutureProvider<DoctorProfile> doctorProfileProvider =
    FutureProvider<DoctorProfile>((Ref ref) async {
  return ref.watch(doctorRepositoryProvider).me();
});

final FutureProvider<List<SpecialtyOption>> specialtiesProvider =
    FutureProvider<List<SpecialtyOption>>((Ref ref) async {
  return ref.watch(doctorRepositoryProvider).specialties();
});

final FutureProvider<Paged<PatientListItem>> patientsProvider =
    FutureProvider<Paged<PatientListItem>>((Ref ref) async {
  return ref.watch(doctorRepositoryProvider).patients();
});

final FutureProvider<Paged<ConsultationListItem>> consultationInboxProvider =
    FutureProvider<Paged<ConsultationListItem>>((Ref ref) async {
  return ref.watch(consultationRepositoryProvider).inbox();
});

final FutureProvider<Paged<ConsultationListItem>> consultationHistoryProvider =
    FutureProvider<Paged<ConsultationListItem>>((Ref ref) async {
  return ref.watch(consultationRepositoryProvider).history();
});

final FutureProvider<Paged<Consultation>> myConsultationsProvider =
    FutureProvider<Paged<Consultation>>((Ref ref) async {
  return ref.watch(consultationRepositoryProvider).mine();
});

final FutureProvider<Wallet> walletProvider = FutureProvider<Wallet>((Ref ref) async {
  return ref.watch(billingRepositoryProvider).wallet();
});

final FutureProvider<Paged<WalletTransaction>> walletTransactionsProvider =
    FutureProvider<Paged<WalletTransaction>>((Ref ref) async {
  return ref.watch(billingRepositoryProvider).transactions();
});

final FutureProvider<SubscriptionStatus> subscriptionProvider =
    FutureProvider<SubscriptionStatus>((Ref ref) async {
  return ref.watch(billingRepositoryProvider).subscription();
});

final FutureProvider<Paged<Escalation>> escalationsProvider =
    FutureProvider<Paged<Escalation>>((Ref ref) async {
  return ref.watch(aiRepositoryProvider).escalations();
});

final FutureProvider<int> unreadNotificationsProvider =
    FutureProvider<int>((Ref ref) async {
  return ref.watch(notificationRepositoryProvider).unreadCount();
});

/// Per-thread clinical data, keyed by thread id so two doctors' data can never
/// share a cache entry.
final FutureProviderFamily<TodayData, String> todayProvider =
    FutureProvider.family<TodayData, String>((Ref ref, String threadId) async {
  return ref.watch(threadRepositoryProvider).today(threadId);
});

final FutureProviderFamily<List<MetricSeries>, String> seriesProvider =
    FutureProvider.family<List<MetricSeries>, String>((Ref ref, String threadId) async {
  return ref.watch(threadRepositoryProvider).series(threadId);
});

final FutureProviderFamily<List<Medication>, String> medicationsProvider =
    FutureProvider.family<List<Medication>, String>((Ref ref, String threadId) async {
  return ref.watch(threadRepositoryProvider).medications(threadId);
});

final FutureProviderFamily<List<Diagnosis>, String> diagnosesProvider =
    FutureProvider.family<List<Diagnosis>, String>((Ref ref, String threadId) async {
  return ref.watch(threadRepositoryProvider).diagnoses(threadId);
});

final FutureProviderFamily<List<ThreadDocument>, String> documentsProvider =
    FutureProvider.family<List<ThreadDocument>, String>((Ref ref, String threadId) async {
  return ref.watch(threadRepositoryProvider).documents(threadId);
});

final FutureProviderFamily<List<AiMessage>, String> aiMessagesProvider =
    FutureProvider.family<List<AiMessage>, String>((Ref ref, String threadId) async {
  return ref.watch(aiRepositoryProvider).messages(threadId);
});
