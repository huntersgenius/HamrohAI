import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';
import '../../../shared/widgets/trend_chart_card.dart';
import 'patient_start_screen.dart';

/// Tab 2 — "Doktorlarim" (spec 5.2).
///
/// Each connected doctor is a separate card. Opening one shows only that
/// doctor's thread; nothing from another doctor is reachable from here.
class PatientDoctorsTab extends ConsumerWidget {
  const PatientDoctorsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<CareThread>> threads = ref.watch(threadsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('patient.my_doctors')),
        actions: <Widget>[
          IconButton(
            tooltip: l10n.t('patient.add_doctor'),
            icon: const Icon(Icons.add_circle_outline_rounded),
            onPressed: () async {
              final bool? connected = await Navigator.of(context).push<bool>(
                MaterialPageRoute<bool>(
                  builder: (_) => const ConnectCodeScreen(),
                ),
              );
              if (connected ?? false) ref.invalidate(threadsProvider);
            },
          ),
        ],
      ),
      body: AsyncView<List<CareThread>>(
        value: threads,
        onRetry: () => ref.invalidate(threadsProvider),
        builder: (List<CareThread> all) {
          final List<CareThread> doctors =
              all.where((CareThread t) => !t.isPersonal).toList();
          final CareThread? personal =
              all.where((CareThread t) => t.isPersonal).firstOrNull;

          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(threadsProvider),
            child: ListView(
              padding: const EdgeInsets.all(AppSpacing.lg),
              children: <Widget>[
                if (doctors.isEmpty)
                  EmptyView(
                    icon: Icons.medical_services_outlined,
                    title: l10n.t('patient.no_doctors'),
                    message: l10n.t('patient.no_doctors_hint'),
                    action: FilledButton.icon(
                      onPressed: () async {
                        final bool? connected = await Navigator.of(context).push<bool>(
                          MaterialPageRoute<bool>(
                            builder: (_) => const ConnectCodeScreen(),
                          ),
                        );
                        if (connected ?? false) {
                          ref.invalidate(threadsProvider);
                        }
                      },
                      icon: const Icon(Icons.add_rounded),
                      label: Text(l10n.t('patient.add_doctor')),
                    ),
                  )
                else
                  for (final CareThread thread in doctors)
                    Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.md),
                      child: _DoctorCard(thread: thread, personal: personal),
                    ),

                // The private container, shown only when it holds something.
                if (personal != null && personal.primaryDiagnosis != null) ...<Widget>[
                  SectionHeader(title: l10n.t('patient.personal_data')),
                  _DoctorCard(thread: personal, personal: null),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}

class _DoctorCard extends StatelessWidget {
  const _DoctorCard({required this.thread, required this.personal});

  final CareThread thread;
  final CareThread? personal;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);

    return AppCard(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PatientThreadScreen(
            thread: thread,
            personalThread: personal,
          ),
        ),
      ),
      child: Row(
        children: <Widget>[
          CircleAvatar(
            radius: 24,
            backgroundColor:
                thread.isPersonal ? AppColors.surfaceAlt : AppColors.primaryLight,
            child: Icon(
              thread.isPersonal
                  ? Icons.lock_outline_rounded
                  : Icons.medical_services_rounded,
              color: thread.isPersonal ? AppColors.textTertiary : AppColors.primaryDark,
              size: 22,
            ),
          ),
          const SizedBox(width: AppSpacing.lg),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  thread.isPersonal
                      ? l10n.t('patient.personal_data')
                      : thread.displayName,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (thread.doctorSpecialty != null)
                  Text(
                    thread.doctorSpecialty!,
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: AppColors.textSecondary,
                    ),
                  ),
                if (thread.primaryDiagnosis != null) ...<Widget>[
                  const SizedBox(height: 4),
                  Text(
                    thread.primaryDiagnosis!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: AppColors.textTertiary,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (thread.doctorRating != null)
            StarRating(rating: thread.doctorRating, size: 13),
          const Icon(Icons.chevron_right_rounded, color: AppColors.textTertiary),
        ],
      ),
    );
  }
}

/// Read-only view of one care thread, from the patient's side (spec 5.2).
class PatientThreadScreen extends ConsumerStatefulWidget {
  const PatientThreadScreen({
    super.key,
    required this.thread,
    this.personalThread,
  });

  final CareThread thread;

  /// Offered for the "share my own records" consent flow.
  final CareThread? personalThread;

  @override
  ConsumerState<PatientThreadScreen> createState() => _PatientThreadScreenState();
}

class _PatientThreadScreenState extends ConsumerState<PatientThreadScreen> {
  final Map<String, TrendData> _trends = <String, TrendData>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadTrends());
  }

  Future<void> _loadTrends() async {
    try {
      final List<MetricSeries> seriesList =
          await ref.read(threadRepositoryProvider).series(widget.thread.id);
      for (final MetricSeries series in seriesList) {
        final TrendData trend = await ref
            .read(threadRepositoryProvider)
            .trend(widget.thread.id, series.id, days: 30);
        if (mounted) setState(() => _trends[series.id] = trend);
      }
    } catch (_) {
      // The section falls back to its empty state.
    }
  }

  Future<void> _export(MetricSeries series) async {
    try {
      final List<int> bytes = await ref
          .read(threadRepositoryProvider)
          .exportSeries(widget.thread.id, series.id);
      final Directory directory = await getTemporaryDirectory();
      final File file = File('${directory.path}/${series.key}.xlsx');
      await file.writeAsBytes(bytes);
      await OpenFilex.open(file.path);
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  Future<void> _sharePersonal() async {
    final AppLocalizations l10n = context.l10n;
    final CareThread? personal = widget.personalThread;
    if (personal == null) return;

    // Explicit consent, with the consequence spelled out (spec 2.2).
    final bool ok = await confirmDialog(
      context,
      title: l10n.t('patient.share_prompt'),
      message: l10n.tp('patient.share_explain', <String, Object?>{
        'doctor': widget.thread.displayName,
      }),
      confirmLabel: l10n.t('patient.share_confirm'),
    );
    if (!ok) return;

    try {
      await ref.read(threadRepositoryProvider).sharePersonal(
            targetThreadId: widget.thread.id,
            sourceThreadId: personal.id,
          );
      ref.invalidate(diagnosesProvider(widget.thread.id));
      ref.invalidate(medicationsProvider(widget.thread.id));
      ref.invalidate(seriesProvider(widget.thread.id));
      await _loadTrends();
      if (mounted) showSuccess(context, l10n.t('common.done'));
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<Diagnosis>> diagnoses =
        ref.watch(diagnosesProvider(widget.thread.id));
    final AsyncValue<List<Medication>> medications =
        ref.watch(medicationsProvider(widget.thread.id));
    final AsyncValue<List<MetricSeries>> series =
        ref.watch(seriesProvider(widget.thread.id));

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.thread.isPersonal
              ? l10n.t('patient.personal_data')
              : widget.thread.displayName,
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(diagnosesProvider(widget.thread.id));
          ref.invalidate(medicationsProvider(widget.thread.id));
          ref.invalidate(seriesProvider(widget.thread.id));
          await _loadTrends();
        },
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: <Widget>[
            if (widget.personalThread != null && !widget.thread.isPersonal)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: OutlinedButton.icon(
                  onPressed: _sharePersonal,
                  icon: const Icon(Icons.folder_shared_outlined, size: 18),
                  label: Text(l10n.t('patient.share_with_doctor')),
                ),
              ),
            SectionHeader(title: l10n.t('doctor.diagnosis')),
            AsyncView<List<Diagnosis>>(
              value: diagnoses,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<Diagnosis> items) {
                if (items.isEmpty) {
                  return _Empty(message: l10n.t('common.empty'));
                }
                return Column(
                  children: items
                      .map(
                        (Diagnosis diagnosis) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.md),
                          child: _PatientDiagnosisCard(
                            threadId: widget.thread.id,
                            diagnosis: diagnosis,
                          ),
                        ),
                      )
                      .toList(),
                );
              },
            ),
            SectionHeader(title: l10n.t('doctor.medications')),
            AsyncView<List<Medication>>(
              value: medications,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<Medication> items) {
                if (items.isEmpty) {
                  return _Empty(message: l10n.t('common.empty'));
                }
                return Column(
                  children: items
                      .map(
                        (Medication medication) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                          child: AppCard(
                            padding: const EdgeInsets.all(AppSpacing.md),
                            child: Row(
                              children: <Widget>[
                                const Icon(
                                  Icons.medication_outlined,
                                  color: AppColors.primary,
                                  size: 20,
                                ),
                                const SizedBox(width: AppSpacing.md),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: <Widget>[
                                      Text(
                                        '${medication.name} · ${medication.dose}',
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                      Text(
                                        medication.times.join(', '),
                                        style: const TextStyle(
                                          fontSize: 12.5,
                                          color: AppColors.textSecondary,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      )
                      .toList(),
                );
              },
            ),
            SectionHeader(title: l10n.t('doctor.trends')),
            AsyncView<List<MetricSeries>>(
              value: series,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<MetricSeries> items) {
                if (items.isEmpty) {
                  return _Empty(message: l10n.t('chart.no_data'));
                }
                return SizedBox(
                  height: 372,
                  child: PageView.builder(
                    controller: PageController(viewportFraction: 0.94),
                    itemCount: items.length,
                    itemBuilder: (BuildContext context, int index) {
                      final MetricSeries item = items[index];
                      final TrendData? trend = _trends[item.id];
                      return Padding(
                        padding: EdgeInsets.only(
                          right: index == items.length - 1 ? 0 : AppSpacing.md,
                        ),
                        child: trend == null
                            ? const Center(
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : TrendChartCard(
                                trend: trend,
                                // Export only: import is doctor-side (spec 5.2).
                                onExport: () => _export(item),
                              ),
                      );
                    },
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _PatientDiagnosisCard extends ConsumerWidget {
  const _PatientDiagnosisCard({
    required this.threadId,
    required this.diagnosis,
  });

  final String threadId;
  final Diagnosis diagnosis;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          VerificationChip(isVerified: diagnosis.isVerified),
          const SizedBox(height: AppSpacing.sm),
          Text(
            diagnosis.text,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
          ),
          if (diagnosis.pendingChangeRequest != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              l10n.t('patient.change_pending'),
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.warning,
                fontWeight: FontWeight.w600,
              ),
            ),
          ] else if (diagnosis.isVerified) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            // A verified diagnosis is read-only here; the patient may only
            // propose a change and the doctor decides (spec 2.3).
            TextButton.icon(
              onPressed: () => _proposeChange(context, ref),
              icon: const Icon(Icons.edit_note_rounded, size: 18),
              label: Text(l10n.t('patient.propose_change')),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _proposeChange(BuildContext context, WidgetRef ref) async {
    final AppLocalizations l10n = context.l10n;
    final TextEditingController comment = TextEditingController();

    final String? text = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(l10n.t('patient.propose_change')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              l10n.t('patient.propose_change_hint'),
              style: const TextStyle(fontSize: 13),
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(controller: comment, maxLines: 3, autofocus: true),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(l10n.t('common.cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(comment.text.trim()),
            child: Text(l10n.t('common.send')),
          ),
        ],
      ),
    );
    if (text == null || text.isEmpty) return;

    try {
      await ref
          .read(threadRepositoryProvider)
          .proposeChange(threadId, diagnosis.id, comment: text);
      ref.invalidate(diagnosesProvider(threadId));
      if (context.mounted) {
        showSuccess(context, l10n.t('patient.change_pending'));
      }
    } catch (error) {
      if (context.mounted) showApiError(context, error);
    }
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Text(
            message,
            style: const TextStyle(color: AppColors.textTertiary),
          ),
        ),
      ),
    );
  }
}
