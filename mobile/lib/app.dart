import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/l10n/app_localizations.dart';
import 'core/providers.dart';
import 'core/theme/app_theme.dart';
import 'features/auth/screens/phone_auth_screen.dart';
import 'features/auth/screens/role_select_screen.dart';
import 'features/auth/screens/welcome_screen.dart';
import 'features/doctor/screens/doctor_register_screen.dart';
import 'features/doctor/screens/doctor_shell.dart';
import 'features/patient/screens/patient_shell.dart';
import 'features/patient/screens/patient_start_screen.dart';
import 'shared/widgets/loading_view.dart';

class HamrohApp extends ConsumerWidget {
  const HamrohApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Locale locale = ref.watch(localeProvider);

    return MaterialApp(
      title: 'Hamroh',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.system,
      locale: locale,
      supportedLocales: AppLocalizations.supportedLocales,
      localizationsDelegates: const <LocalizationsDelegate<dynamic>>[
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      localeResolutionCallback: (Locale? device, Iterable<Locale> supported) {
        // Uzbek is the product's primary language, so it is also the fallback
        // for any device locale we do not ship.
        if (device == null) return const Locale('uz');
        for (final Locale candidate in supported) {
          if (candidate.languageCode == device.languageCode) return candidate;
        }
        return const Locale('uz');
      },
      home: const _RootGate(),
    );
  }
}

/// Chooses the screen from the onboarding stage.
///
/// The gate is deliberately a single switch rather than a route table: the
/// sequence is linear and mandatory (spec 3), and a user must not be able to
/// deep-link past the phone-verification step.
class _RootGate extends ConsumerWidget {
  const _RootGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final SessionState session = ref.watch(sessionProvider);

    return switch (session.stage) {
      SessionStage.loading => const Scaffold(body: LoadingView()),
      SessionStage.signedOut => const WelcomeScreen(),
      // No skip button exists on this screen — that is the point.
      SessionStage.needsPhone => PhoneAuthScreen(
          onboardingToken: session.onboardingToken,
        ),
      SessionStage.needsRole => const RoleSelectScreen(),
      SessionStage.needsProfile =>
        session.isDoctor ? const DoctorRegisterScreen() : const PatientStartScreen(),
      SessionStage.ready => session.isDoctor ? const DoctorShell() : const PatientShell(),
    };
  }
}
