import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';
import 'add_patient_screen.dart';
import 'escalations_screen.dart';
import 'patient_detail_screen.dart';

/// Tab 1 — "Bemorlarim" (spec 4.2).
class DoctorPatientsTab extends ConsumerStatefulWidget {
  const DoctorPatientsTab({super.key});

  @override
  ConsumerState<DoctorPatientsTab> createState() => _DoctorPatientsTabState();
}

class _DoctorPatientsTabState extends ConsumerState<DoctorPatientsTab> {
  final TextEditingController _searchController = TextEditingController();
  String _search = '';

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<Paged<PatientListItem>> patients = ref.watch(patientsProvider);
    final AsyncValue<Paged<Escalation>> escalations = ref.watch(escalationsProvider);

    final int openEscalations = escalations.asData?.value.items.length ?? 0;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('doctor.tab_patients')),
        actions: <Widget>[
          if (openEscalations > 0)
            Padding(
              padding: const EdgeInsets.only(right: AppSpacing.sm),
              child: Badge.count(
                count: openEscalations,
                child: IconButton(
                  icon: const Icon(Icons.mark_unread_chat_alt_outlined),
                  tooltip: l10n.t('doctor.escalations'),
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => const EscalationsScreen(),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final bool? created = await Navigator.of(context).push<bool>(
            MaterialPageRoute<bool>(builder: (_) => const AddPatientScreen()),
          );
          if (created ?? false) ref.invalidate(patientsProvider);
        },
        icon: const Icon(Icons.person_add_alt_1_rounded),
        label: Text(l10n.t('doctor.add_patient')),
      ),
      body: SafeArea(
        child: Column(
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.sm,
                AppSpacing.lg,
                AppSpacing.sm,
              ),
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: l10n.t('common.search'),
                  prefixIcon: const Icon(Icons.search_rounded),
                  isDense: true,
                  suffixIcon: _search.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.clear_rounded),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _search = '');
                          },
                        ),
                ),
                onChanged: (String value) => setState(() => _search = value),
              ),
            ),
            Expanded(
              child: AsyncView<Paged<PatientListItem>>(
                value: patients,
                onRetry: () => ref.invalidate(patientsProvider),
                builder: (Paged<PatientListItem> page) {
                  final List<PatientListItem> items = _search.isEmpty
                      ? page.items
                      : page.items
                          .where((PatientListItem item) =>
                              item.fullName.toLowerCase().contains(_search.toLowerCase()))
                          .toList();

                  if (items.isEmpty) {
                    return EmptyView(
                      icon: Icons.people_outline_rounded,
                      title: l10n.t('doctor.no_patients'),
                      message: l10n.t('doctor.no_patients_hint'),
                    );
                  }

                  return RefreshIndicator(
                    onRefresh: () async {
                      ref.invalidate(patientsProvider);
                      ref.invalidate(escalationsProvider);
                    },
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(
                        AppSpacing.lg,
                        AppSpacing.sm,
                        AppSpacing.lg,
                        96,
                      ),
                      itemCount: items.length,
                      separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
                      itemBuilder: (BuildContext context, int index) => _PatientCard(
                        item: items[index],
                        onTap: () => _openPatient(items[index]),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openPatient(PatientListItem item) {
    if (item.isPendingInvite) {
      // No thread exists yet — show the code so it can be re-shared.
      showDialog<void>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: Text(item.fullName),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              CodeDisplay(
                code: item.pendingInviteCode ?? '',
                hint: context.l10n.t('doctor.code_hint'),
              ),
            ],
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: Text(context.l10n.t('common.close')),
            ),
          ],
        ),
      );
      return;
    }

    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PatientDetailScreen(
          threadId: item.careThreadId,
          patientName: item.fullName,
        ),
      ),
    );
  }
}

class _PatientCard extends StatelessWidget {
  const _PatientCard({required this.item, required this.onTap});

  final PatientListItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);

    return AppCard(
      onTap: onTap,
      border: item.riskLevel == 'red' ? AppColors.danger.withValues(alpha: 0.4) : null,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CircleAvatar(
            radius: 24,
            backgroundColor:
                item.isPendingInvite ? AppColors.surfaceAlt : AppColors.primaryLight,
            child: item.isPendingInvite
                ? const Icon(Icons.hourglass_empty_rounded,
                    color: AppColors.textTertiary, size: 20)
                : Text(
                    Formatters.initials(item.fullName),
                    style: const TextStyle(
                      color: AppColors.primaryDark,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
          ),
          const SizedBox(width: AppSpacing.lg),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  children: <Widget>[
                    Expanded(
                      child: Text(
                        item.fullName,
                        style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (!item.isPendingInvite)
                      RiskBadge(level: item.riskLevel, compact: true),
                  ],
                ),
                if (item.primaryDiagnosis != null) ...<Widget>[
                  const SizedBox(height: 3),
                  Text(
                    item.primaryDiagnosis!,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: AppColors.textSecondary,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
                const SizedBox(height: AppSpacing.sm),
                Row(
                  children: <Widget>[
                    if (item.isPendingInvite)
                      _Tag(
                        label: l10n.t('doctor.pending_invite'),
                        color: AppColors.warning,
                      )
                    else
                      Text(
                        Formatters.relative(
                          item.lastActivityAt,
                          l10n.languageCode,
                        ),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: AppColors.textTertiary,
                          fontSize: 12,
                        ),
                      ),
                    if (item.openEscalations > 0) ...<Widget>[
                      const SizedBox(width: AppSpacing.sm),
                      _Tag(
                        label: '${item.openEscalations} savol',
                        color: AppColors.info,
                      ),
                    ],
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

class _Tag extends StatelessWidget {
  const _Tag({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11.5,
          color: color,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
