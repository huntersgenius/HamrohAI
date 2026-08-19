import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import 'patient_doctors_tab.dart';
import 'patient_help_tab.dart';
import 'patient_profile_tab.dart';
import 'patient_today_tab.dart';

/// Patient bottom-tab navigation (spec 5.2).
class PatientShell extends ConsumerStatefulWidget {
  const PatientShell({super.key});

  @override
  ConsumerState<PatientShell> createState() => _PatientShellState();
}

class _PatientShellState extends ConsumerState<PatientShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: const <Widget>[
          PatientTodayTab(),
          PatientDoctorsTab(),
          PatientHelpTab(),
          PatientProfileTab(),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (int value) => setState(() => _index = value),
        items: <BottomNavigationBarItem>[
          BottomNavigationBarItem(
            icon: const Icon(Icons.today_outlined),
            activeIcon: const Icon(Icons.today_rounded),
            label: l10n.t('patient.tab_today'),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.medical_services_outlined),
            activeIcon: const Icon(Icons.medical_services_rounded),
            label: l10n.t('patient.tab_doctors'),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.support_agent_outlined),
            activeIcon: const Icon(Icons.support_agent_rounded),
            label: l10n.t('patient.tab_help'),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.person_outline_rounded),
            activeIcon: const Icon(Icons.person_rounded),
            label: l10n.t('patient.tab_profile'),
          ),
        ],
      ),
    );
  }
}
