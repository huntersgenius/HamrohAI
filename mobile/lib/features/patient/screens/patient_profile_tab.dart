import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Tab 4 — profile, language, notifications and the voice-call reminder
/// setting (spec 5.2 tab 4, plus the IVR section of the spec).
class PatientProfileTab extends ConsumerWidget {
  const PatientProfileTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final SessionState session = ref.watch(sessionProvider);
    final AppUser? user = session.user;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('patient.profile'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: <Widget>[
          AppCard(
            child: Row(
              children: <Widget>[
                CircleAvatar(
                  radius: 28,
                  backgroundColor: AppColors.primaryLight,
                  child: Text(
                    Formatters.initials(user?.fullName),
                    style: const TextStyle(
                      color: AppColors.primaryDark,
                      fontWeight: FontWeight.w700,
                      fontSize: 18,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        user?.fullName ?? '',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                      Text(
                        Formatters.phone(user?.phone ?? ''),
                        style: const TextStyle(color: AppColors.textSecondary),
                      ),
                      if (user?.birthDate != null)
                        Text(
                          Formatters.date(user!.birthDate!, l10n.languageCode),
                          style: const TextStyle(
                            fontSize: 12.5,
                            color: AppColors.textTertiary,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          // ------------------------------------------------- reminders
          SectionHeader(title: l10n.t('doctor.notifications')),
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: <Widget>[
                // On by default, but the patient must be able to switch it off.
                SwitchListTile(
                  value: user?.ivrRemindersEnabled ?? true,
                  title: Text(l10n.t('patient.call_reminders')),
                  subtitle: Text(
                    l10n.t('patient.call_reminders_hint'),
                    style: const TextStyle(fontSize: 12),
                  ),
                  secondary: const Icon(Icons.phone_in_talk_outlined),
                  onChanged: (bool value) async {
                    try {
                      await ref.read(sessionProvider.notifier).updateUser(
                        <String, dynamic>{'ivr_reminders_enabled': value},
                      );
                    } catch (error) {
                      if (context.mounted) showApiError(context, error);
                    }
                  },
                ),
                const Divider(height: 1),
                _PreferenceSwitch(
                  label: l10n.t('patient.notify_medication'),
                  prefKey: 'medication',
                  user: user,
                ),
                const Divider(height: 1),
                _PreferenceSwitch(
                  label: l10n.t('patient.notify_checkin'),
                  prefKey: 'checkin',
                  user: user,
                ),
              ],
            ),
          ),

          // -------------------------------------------------- language
          SectionHeader(title: l10n.t('common.language')),
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: <Widget>[
                for (final MapEntry<String, String> entry in <String, String>{
                  'uz': "O'zbek",
                  'ru': 'Русский',
                  'en': 'English',
                }.entries)
                  RadioListTile<String>(
                    value: entry.key,
                    groupValue: l10n.languageCode,
                    title: Text(entry.value),
                    onChanged: (String? value) async {
                      if (value == null) return;
                      await ref.read(localeProvider.notifier).set(value);
                      await ref
                          .read(sessionProvider.notifier)
                          .updateUser(<String, dynamic>{'locale': value});
                    },
                  ),
              ],
            ),
          ),

          const SizedBox(height: AppSpacing.xl),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
            onPressed: () async {
              final bool ok = await confirmDialog(
                context,
                title: l10n.t('common.logout_confirm'),
                confirmLabel: l10n.t('common.logout'),
                destructive: true,
              );
              if (ok) await ref.read(sessionProvider.notifier).signOut();
            },
            icon: const Icon(Icons.logout_rounded),
            label: Text(l10n.t('common.logout')),
          ),
          const SizedBox(height: AppSpacing.xxl),
        ],
      ),
    );
  }
}

class _PreferenceSwitch extends ConsumerWidget {
  const _PreferenceSwitch({
    required this.label,
    required this.prefKey,
    required this.user,
  });

  final String label;
  final String prefKey;
  final AppUser? user;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SwitchListTile(
      value: user?.prefers(prefKey) ?? true,
      title: Text(label),
      onChanged: (bool next) async {
        final Map<String, dynamic> preferences = Map<String, dynamic>.from(
          user?.notifyPreferences ?? <String, dynamic>{},
        );
        preferences[prefKey] = next;
        try {
          await ref.read(sessionProvider.notifier).updateUser(
            <String, dynamic>{'notify_preferences': preferences},
          );
        } catch (error) {
          if (context.mounted) showApiError(context, error);
        }
      },
    );
  }
}
