import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../data/models/models.dart';
import '../../../shared/widgets/loading_view.dart';
import 'doctor_consultations_tab.dart';
import 'doctor_patients_tab.dart';
import 'doctor_register_screen.dart';
import 'doctor_settings_tab.dart';
import 'doctor_wallet_tab.dart';

/// Doctor bottom-tab navigation (spec 4.2).
class DoctorShell extends ConsumerStatefulWidget {
  const DoctorShell({super.key});

  @override
  ConsumerState<DoctorShell> createState() => _DoctorShellState();
}

class _DoctorShellState extends ConsumerState<DoctorShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<DoctorProfile> profile = ref.watch(doctorProfileProvider);

    return profile.when(
      loading: () => const Scaffold(body: LoadingView()),
      error: (Object error, StackTrace _) => Scaffold(
        body: ErrorView(
          error: error,
          onRetry: () => ref.invalidate(doctorProfileProvider),
        ),
      ),
      data: (DoctorProfile doctor) {
        // An unapproved licence blocks the practice tabs entirely; approval is
        // a manual database step in the MVP (spec 1).
        if (!doctor.isApproved) return const DoctorPendingScreen();

        final List<Widget> tabs = <Widget>[
          const DoctorPatientsTab(),
          const DoctorConsultationsTab(),
          const DoctorWalletTab(),
          const DoctorSettingsTab(),
        ];

        return Scaffold(
          body: IndexedStack(index: _index, children: tabs),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: _index,
            onTap: (int value) => setState(() => _index = value),
            items: <BottomNavigationBarItem>[
              BottomNavigationBarItem(
                icon: const Icon(Icons.people_outline_rounded),
                activeIcon: const Icon(Icons.people_rounded),
                label: l10n.t('doctor.tab_patients'),
              ),
              BottomNavigationBarItem(
                icon: const Icon(Icons.forum_outlined),
                activeIcon: const Icon(Icons.forum_rounded),
                label: l10n.t('doctor.tab_consultations'),
              ),
              BottomNavigationBarItem(
                icon: const Icon(Icons.account_balance_wallet_outlined),
                activeIcon: const Icon(Icons.account_balance_wallet_rounded),
                label: l10n.t('doctor.tab_wallet'),
              ),
              BottomNavigationBarItem(
                icon: const Icon(Icons.settings_outlined),
                activeIcon: const Icon(Icons.settings_rounded),
                label: l10n.t('doctor.tab_settings'),
              ),
            ],
          ),
        );
      },
    );
  }
}
