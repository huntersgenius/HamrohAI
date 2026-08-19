import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Tab 4 — profile, consultation availability, connect code, subscription
/// and notification preferences (spec 4.2).
class DoctorSettingsTab extends ConsumerWidget {
  const DoctorSettingsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<DoctorProfile> profile = ref.watch(doctorProfileProvider);
    final SessionState session = ref.watch(sessionProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('doctor.tab_settings'))),
      body: AsyncView<DoctorProfile>(
        value: profile,
        onRetry: () => ref.invalidate(doctorProfileProvider),
        builder: (DoctorProfile doctor) => ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: <Widget>[
            _ProfileHeader(doctor: doctor),
            const SizedBox(height: AppSpacing.lg),

            // ------------------------------------------- connect code
            SectionHeader(title: l10n.t('doctor.connect_code')),
            AppCard(
              child: Column(
                children: <Widget>[
                  CodeDisplay(
                    code: doctor.connectCode,
                    hint: l10n.t('doctor.connect_code_hint'),
                  ),
                ],
              ),
            ),

            // -------------------------------------- consultation setup
            SectionHeader(title: l10n.t('doctor.tab_consultations')),
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: <Widget>[
                  SwitchListTile(
                    value: doctor.consultationOpen,
                    title: Text(l10n.t('doctor.open_for_consultations')),
                    onChanged: (bool value) async {
                      try {
                        await ref
                            .read(doctorRepositoryProvider)
                            .updateConsultationSettings(
                          <String, dynamic>{'consultation_open': value},
                        );
                        ref.invalidate(doctorProfileProvider);
                      } catch (error) {
                        if (context.mounted) showApiError(context, error);
                      }
                    },
                  ),
                  const Divider(height: 1),
                  ListTile(
                    title: Text(l10n.t('doctor.consultation_price')),
                    subtitle: Text(
                      Formatters.money(
                        doctor.consultationPriceUzs ?? 0,
                        l10n.languageCode,
                      ),
                    ),
                    trailing: const Icon(Icons.edit_outlined, size: 20),
                    onTap: () => _editPrice(context, ref, doctor),
                  ),
                ],
              ),
            ),

            // ------------------------------------------- subscription
            SectionHeader(title: l10n.t('doctor.subscription')),
            const _SubscriptionCard(),

            // ------------------------------------------ notifications
            SectionHeader(title: l10n.t('doctor.notifications')),
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: <Widget>[
                  _NotifySwitch(
                    label: l10n.t('doctor.notify_new_patient'),
                    prefKey: 'new_patient',
                    user: session.user,
                  ),
                  const Divider(height: 1),
                  _NotifySwitch(
                    label: l10n.t('doctor.notify_new_consultation'),
                    prefKey: 'new_consultation',
                    user: session.user,
                  ),
                  const Divider(height: 1),
                  _NotifySwitch(
                    label: l10n.t('doctor.notify_wallet'),
                    prefKey: 'wallet',
                    user: session.user,
                  ),
                ],
              ),
            ),

            // ------------------------------------------------ language
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
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.danger,
              ),
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
      ),
    );
  }

  Future<void> _editPrice(
    BuildContext context,
    WidgetRef ref,
    DoctorProfile doctor,
  ) async {
    final AppLocalizations l10n = context.l10n;
    final TextEditingController controller = TextEditingController(
      text: '${doctor.consultationPriceUzs ?? ''}',
    );
    final String? value = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(l10n.t('doctor.consultation_price')),
        content: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          autofocus: true,
          decoration: InputDecoration(suffixText: l10n.t('common.sum')),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(l10n.t('common.cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: Text(l10n.t('common.save')),
          ),
        ],
      ),
    );
    final int? price = int.tryParse(value ?? '');
    if (price == null) return;

    try {
      await ref.read(doctorRepositoryProvider).updateConsultationSettings(
        <String, dynamic>{'consultation_price_uzs': price},
      );
      ref.invalidate(doctorProfileProvider);
    } catch (error) {
      if (context.mounted) showApiError(context, error);
    }
  }
}

class _ProfileHeader extends StatelessWidget {
  const _ProfileHeader({required this.doctor});

  final DoctorProfile doctor;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        children: <Widget>[
          CircleAvatar(
            radius: 28,
            backgroundColor: AppColors.primaryLight,
            child: Text(
              Formatters.initials(doctor.fullName),
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
                  doctor.fullName,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
                Text(
                  doctor.specialty,
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
                const SizedBox(height: 4),
                Row(
                  children: <Widget>[
                    StarRating(
                      rating: doctor.ratingAverage,
                      count: doctor.ratingCount,
                      size: 14,
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Text(
                      '${doctor.patientCount}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.textTertiary,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SubscriptionCard extends ConsumerWidget {
  const _SubscriptionCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<SubscriptionStatus> subscription = ref.watch(subscriptionProvider);

    return AsyncView<SubscriptionStatus>(
      value: subscription,
      loading: const LinearProgressIndicator(minHeight: 2),
      builder: (SubscriptionStatus status) {
        final String label = switch (status.status) {
          'active' => l10n.tp('doctor.subscription_active', <String, Object?>{
              'date': status.currentPeriodEnd == null
                  ? ''
                  : Formatters.date(
                      status.currentPeriodEnd!,
                      l10n.languageCode,
                    ),
            }),
          'trial' => l10n.tp('doctor.subscription_trial', <String, Object?>{
              'date': status.currentPeriodEnd == null
                  ? ''
                  : Formatters.date(
                      status.currentPeriodEnd!,
                      l10n.languageCode,
                    ),
            }),
          _ => l10n.t('doctor.subscription_expired'),
        };

        return AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Icon(
                    status.isActive
                        ? Icons.verified_rounded
                        : Icons.error_outline_rounded,
                    color: status.isActive ? AppColors.ok : AppColors.warning,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      label,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
              if (!status.isActive || status.status == 'trial') ...<Widget>[
                const SizedBox(height: AppSpacing.lg),
                FilledButton(
                  onPressed: () => _subscribe(context, ref, 'monthly'),
                  child: Text(
                    l10n.tp('doctor.subscribe_monthly', <String, Object?>{
                      'amount': Formatters.money(
                        status.monthlyPriceUzs,
                        l10n.languageCode,
                      ),
                    }),
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                OutlinedButton(
                  onPressed: () => _subscribe(context, ref, 'yearly'),
                  child: Text(
                    l10n.tp('doctor.subscribe_yearly', <String, Object?>{
                      'amount': Formatters.money(
                        status.yearlyPriceUzs,
                        l10n.languageCode,
                      ),
                    }),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Future<void> _subscribe(
    BuildContext context,
    WidgetRef ref,
    String plan,
  ) async {
    final String? provider = await _pickProvider(context);
    if (provider == null) return;

    try {
      final CheckoutInfo checkout = await ref
          .read(billingRepositoryProvider)
          .subscribe(plan: plan, provider: provider);
      final Uri uri = Uri.parse(checkout.checkoutUrl);
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
      // The webhook activates the subscription; refresh when the user returns.
      ref.invalidate(subscriptionProvider);
    } catch (error) {
      if (context.mounted) showApiError(context, error);
    }
  }
}

/// Click / Payme chooser (spec 1: both providers ship).
Future<String?> _pickProvider(BuildContext context) {
  final AppLocalizations l10n = context.l10n;
  return showModalBottomSheet<String>(
    context: context,
    builder: (BuildContext context) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Text(
              l10n.t('patient.choose_payment'),
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.payment_rounded),
            title: const Text('Click'),
            onTap: () => Navigator.of(context).pop('click'),
          ),
          ListTile(
            leading: const Icon(Icons.credit_card_rounded),
            title: const Text('Payme'),
            onTap: () => Navigator.of(context).pop('payme'),
          ),
          const SizedBox(height: AppSpacing.lg),
        ],
      ),
    ),
  );
}

class _NotifySwitch extends ConsumerWidget {
  const _NotifySwitch({
    required this.label,
    required this.prefKey,
    required this.user,
  });

  final String label;
  final String prefKey;
  final AppUser? user;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool value = user?.prefers(prefKey) ?? true;
    return SwitchListTile(
      value: value,
      title: Text(label),
      onChanged: (bool next) async {
        final Map<String, dynamic> preferences =
            Map<String, dynamic>.from(user?.notifyPreferences ?? <String, dynamic>{});
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
