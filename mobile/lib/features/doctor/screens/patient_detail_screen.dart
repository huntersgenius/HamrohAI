import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';
import '../../../shared/widgets/trend_chart_card.dart';
import 'medication_editor.dart';

/// One patient, seen through one care thread.
///
/// Everything on this screen is scoped to [threadId]; the API refuses any id
/// from another doctor's thread, so a doctor physically cannot reach a
/// colleague's data for the same patient (spec 2.2).
class PatientDetailScreen extends ConsumerStatefulWidget {
  const PatientDetailScreen({
    super.key,
    required this.threadId,
    required this.patientName,
  });

  final String threadId;
  final String patientName;

  @override
  ConsumerState<PatientDetailScreen> createState() => _PatientDetailScreenState();
}

class _PatientDetailScreenState extends ConsumerState<PatientDetailScreen> {
  final Map<String, TrendData> _trends = <String, TrendData>{};
  bool _loadingTrends = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadTrends());
  }

  Future<void> _loadTrends() async {
    setState(() => _loadingTrends = true);
    try {
      final List<MetricSeries> seriesList =
          await ref.read(threadRepositoryProvider).series(widget.threadId);
      for (final MetricSeries series in seriesList) {
        final TrendData trend = await ref
            .read(threadRepositoryProvider)
            .trend(widget.threadId, series.id, days: 30);
        if (mounted) setState(() => _trends[series.id] = trend);
      }
    } catch (_) {
      // The charts section shows its own empty state.
    } finally {
      if (mounted) setState(() => _loadingTrends = false);
    }
  }

  Future<void> _exportSeries(MetricSeries series) async {
    final AppLocalizations l10n = context.l10n;
    try {
      final List<int> bytes = await ref
          .read(threadRepositoryProvider)
          .exportSeries(widget.threadId, series.id);
      final Directory directory = await getTemporaryDirectory();
      final File file = File(
        '${directory.path}/${series.key}-${DateTime.now().millisecondsSinceEpoch}.xlsx',
      );
      await file.writeAsBytes(bytes);
      await OpenFilex.open(file.path);
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
    if (mounted) {
      // Nothing to refresh, but keep the user informed the file was produced.
      showSuccess(context, l10n.t('common.done'));
    }
  }

  Future<void> _importSeries(MetricSeries series) async {
    final AppLocalizations l10n = context.l10n;
    final FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: <String>['xlsx', 'xls'],
    );
    final String? path = result?.files.single.path;
    if (path == null) return;

    try {
      final Map<String, dynamic> response =
          await ref.read(threadRepositoryProvider).importSeries(
                widget.threadId,
                series.id,
                filePath: path,
                filename: result!.files.single.name,
              );
      if (!mounted) return;
      showSuccess(
        context,
        l10n.tp('chart.imported', <String, Object?>{
          'count': response['imported'] ?? 0,
        }),
      );
      await _loadTrends();
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  Future<void> _addReading(MetricSeries series) async {
    final bool? added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => AddReadingSheet(
        threadId: widget.threadId,
        series: series,
      ),
    );
    if (added ?? false) await _loadTrends();
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<List<Diagnosis>> diagnoses =
        ref.watch(diagnosesProvider(widget.threadId));
    final AsyncValue<List<Medication>> medications =
        ref.watch(medicationsProvider(widget.threadId));
    final AsyncValue<List<MetricSeries>> series =
        ref.watch(seriesProvider(widget.threadId));
    final AsyncValue<List<ThreadDocument>> documents =
        ref.watch(documentsProvider(widget.threadId));

    return Scaffold(
      appBar: AppBar(title: Text(widget.patientName)),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(diagnosesProvider(widget.threadId));
          ref.invalidate(medicationsProvider(widget.threadId));
          ref.invalidate(seriesProvider(widget.threadId));
          ref.invalidate(documentsProvider(widget.threadId));
          await _loadTrends();
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.xxl,
          ),
          children: <Widget>[
            // ------------------------------------------------- diagnoses
            SectionHeader(title: l10n.t('doctor.diagnosis')),
            AsyncView<List<Diagnosis>>(
              value: diagnoses,
              loading: const Padding(
                padding: EdgeInsets.all(AppSpacing.lg),
                child: LinearProgressIndicator(minHeight: 2),
              ),
              builder: (List<Diagnosis> items) {
                if (items.isEmpty) {
                  return _AddDiagnosisTile(threadId: widget.threadId);
                }
                return Column(
                  children: <Widget>[
                    for (final Diagnosis diagnosis in items)
                      Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.md),
                        child: _DiagnosisCard(
                          threadId: widget.threadId,
                          diagnosis: diagnosis,
                        ),
                      ),
                    _AddDiagnosisTile(threadId: widget.threadId),
                  ],
                );
              },
            ),

            // ----------------------------------------------- medications
            SectionHeader(
              title: l10n.t('doctor.medications'),
              action: TextButton.icon(
                onPressed: () async {
                  final bool? saved = await Navigator.of(context).push<bool>(
                    MaterialPageRoute<bool>(
                      builder: (_) => MedicationEditor(threadId: widget.threadId),
                    ),
                  );
                  if (saved ?? false) {
                    ref.invalidate(medicationsProvider(widget.threadId));
                  }
                },
                icon: const Icon(Icons.add_rounded, size: 18),
                label: Text(l10n.t('common.add')),
              ),
            ),
            AsyncView<List<Medication>>(
              value: medications,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<Medication> items) {
                if (items.isEmpty) {
                  return _EmptyCard(message: l10n.t('common.empty'));
                }
                return Column(
                  children: items
                      .map(
                        (Medication medication) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.md),
                          child: _MedicationRow(
                            threadId: widget.threadId,
                            medication: medication,
                          ),
                        ),
                      )
                      .toList(),
                );
              },
            ),

            // ---------------------------------------------- trend charts
            SectionHeader(title: l10n.t('doctor.trends')),
            AsyncView<List<MetricSeries>>(
              value: series,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<MetricSeries> items) {
                if (items.isEmpty) {
                  return _EmptyCard(message: l10n.t('chart.no_data'));
                }
                // Horizontally swipeable cards, one chart per indicator.
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
                                isLoading: _loadingTrends,
                                onExport: () => _exportSeries(item),
                                onImport: () => _importSeries(item),
                                onAddReading: () => _addReading(item),
                              ),
                      );
                    },
                  ),
                );
              },
            ),

            // ------------------------------------------------- documents
            SectionHeader(title: l10n.t('doctor.documents')),
            AsyncView<List<ThreadDocument>>(
              value: documents,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (List<ThreadDocument> items) {
                if (items.isEmpty) {
                  return _EmptyCard(message: l10n.t('doctor.no_documents'));
                }
                return Column(
                  children: items
                      .map(
                        (ThreadDocument document) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                          child: AppCard(
                            padding: const EdgeInsets.all(AppSpacing.md),
                            onTap: () async {
                              final String? url = document.downloadUrl;
                              if (url == null) return;
                              final Uri uri = Uri.parse(url);
                              if (await canLaunchUrl(uri)) {
                                await launchUrl(
                                  uri,
                                  mode: LaunchMode.externalApplication,
                                );
                              }
                            },
                            child: Row(
                              children: <Widget>[
                                Icon(
                                  document.isPdf
                                      ? Icons.picture_as_pdf_rounded
                                      : Icons.image_rounded,
                                  color: AppColors.primary,
                                ),
                                const SizedBox(width: AppSpacing.md),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: <Widget>[
                                      Text(
                                        document.filename,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                      Text(
                                        Formatters.fileSize(document.sizeBytes),
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: AppColors.textTertiary,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const Icon(
                                  Icons.open_in_new_rounded,
                                  size: 18,
                                  color: AppColors.textTertiary,
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
          ],
        ),
      ),
    );
  }
}

class _DiagnosisCard extends ConsumerWidget {
  const _DiagnosisCard({required this.threadId, required this.diagnosis});

  final String threadId;
  final Diagnosis diagnosis;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final ChangeRequest? pending = diagnosis.pendingChangeRequest;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(child: VerificationChip(isVerified: diagnosis.isVerified)),
              if (!diagnosis.isVerified)
                TextButton(
                  onPressed: () async {
                    try {
                      await ref
                          .read(threadRepositoryProvider)
                          .verifyDiagnosis(threadId, diagnosis.id);
                      ref.invalidate(diagnosesProvider(threadId));
                      ref.invalidate(seriesProvider(threadId));
                    } catch (error) {
                      if (context.mounted) showApiError(context, error);
                    }
                  },
                  child: Text(l10n.t('common.confirm')),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            diagnosis.text,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
          ),
          if (diagnosis.templateName != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: <Widget>[
                const Icon(
                  Icons.dataset_outlined,
                  size: 14,
                  color: AppColors.textTertiary,
                ),
                const SizedBox(width: 5),
                Text(
                  diagnosis.templateName!,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ],
          // The patient's "O'zgartirish taklif qilish" request (spec 2.3).
          if (pending != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.warningSoft,
                borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    l10n.t('patient.propose_change'),
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.warning,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(pending.comment, style: const TextStyle(fontSize: 13)),
                  if (pending.proposedText != null) ...<Widget>[
                    const SizedBox(height: 4),
                    Text(
                      '→ ${pending.proposedText}',
                      style: const TextStyle(
                        fontSize: 13,
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ],
                  const SizedBox(height: AppSpacing.sm),
                  Row(
                    children: <Widget>[
                      TextButton(
                        onPressed: () => _resolve(context, ref, pending, false),
                        child: Text(l10n.t('common.no')),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      FilledButton(
                        onPressed: () => _resolve(context, ref, pending, true),
                        style: FilledButton.styleFrom(
                          minimumSize: const Size(0, 38),
                        ),
                        child: Text(l10n.t('common.confirm')),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _resolve(
    BuildContext context,
    WidgetRef ref,
    ChangeRequest request,
    bool accept,
  ) async {
    try {
      await ref.read(threadRepositoryProvider).resolveChange(
            threadId,
            request.id,
            accept: accept,
          );
      ref.invalidate(diagnosesProvider(threadId));
    } catch (error) {
      if (context.mounted) showApiError(context, error);
    }
  }
}

class _AddDiagnosisTile extends ConsumerStatefulWidget {
  const _AddDiagnosisTile({required this.threadId});

  final String threadId;

  @override
  ConsumerState<_AddDiagnosisTile> createState() => _AddDiagnosisTileState();
}

class _AddDiagnosisTileState extends ConsumerState<_AddDiagnosisTile> {
  Future<void> _add() async {
    final AppLocalizations l10n = context.l10n;
    final TextEditingController controller = TextEditingController();
    final String? text = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(l10n.t('doctor.diagnosis')),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLines: 3,
          decoration: InputDecoration(hintText: l10n.t('doctor.diagnosis')),
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
    if (text == null || text.isEmpty) return;

    try {
      // The server auto-matches the template and applies it (spec 6).
      await ref
          .read(threadRepositoryProvider)
          .createDiagnosis(widget.threadId, text: text);
      ref.invalidate(diagnosesProvider(widget.threadId));
      ref.invalidate(seriesProvider(widget.threadId));
    } catch (error) {
      if (mounted) showApiError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: _add,
      icon: const Icon(Icons.add_rounded, size: 18),
      label: Text(context.l10n.t('common.add')),
    );
  }
}

class _MedicationRow extends ConsumerWidget {
  const _MedicationRow({required this.threadId, required this.medication});

  final String threadId;
  final Medication medication;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final double? adherence = medication.adherence7d;

    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  '${medication.name} · ${medication.dose}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  medication.times.join(', '),
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.textSecondary,
                  ),
                ),
                if (adherence != null) ...<Widget>[
                  const SizedBox(height: 5),
                  Row(
                    children: <Widget>[
                      Text(
                        '${l10n.t('doctor.adherence')}: ',
                        style: const TextStyle(
                          fontSize: 11.5,
                          color: AppColors.textTertiary,
                        ),
                      ),
                      Text(
                        '${adherence.toStringAsFixed(0)}%',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                          color: adherence >= 80
                              ? AppColors.ok
                              : (adherence >= 50 ? AppColors.warning : AppColors.danger),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.edit_outlined, size: 20),
            onPressed: () async {
              final bool? saved = await Navigator.of(context).push<bool>(
                MaterialPageRoute<bool>(
                  builder: (_) => MedicationEditor(
                    threadId: threadId,
                    medication: medication,
                  ),
                ),
              );
              if (saved ?? false) ref.invalidate(medicationsProvider(threadId));
            },
          ),
          IconButton(
            icon: const Icon(
              Icons.delete_outline_rounded,
              size: 20,
              color: AppColors.danger,
            ),
            onPressed: () async {
              final bool ok = await confirmDialog(
                context,
                title: medication.name,
                message: l10n.t('common.delete'),
                destructive: true,
              );
              if (!ok) return;
              try {
                await ref
                    .read(threadRepositoryProvider)
                    .deleteMedication(threadId, medication.id);
                ref.invalidate(medicationsProvider(threadId));
              } catch (error) {
                if (context.mounted) showApiError(context, error);
              }
            },
          ),
        ],
      ),
    );
  }
}

class _EmptyCard extends StatelessWidget {
  const _EmptyCard({required this.message});

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

/// Manual reading entry, used by both roles.
class AddReadingSheet extends ConsumerStatefulWidget {
  const AddReadingSheet({
    super.key,
    required this.threadId,
    required this.series,
  });

  final String threadId;
  final MetricSeries series;

  @override
  ConsumerState<AddReadingSheet> createState() => _AddReadingSheetState();
}

class _AddReadingSheetState extends ConsumerState<AddReadingSheet> {
  final TextEditingController _value = TextEditingController();
  final TextEditingController _secondary = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _value.dispose();
    _secondary.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final double? value = double.tryParse(_value.text.replaceAll(',', '.'));
    if (value == null) return;
    setState(() => _busy = true);
    try {
      await ref.read(threadRepositoryProvider).addReading(
            widget.threadId,
            widget.series.id,
            value: value,
            valueSecondary: widget.series.isPair
                ? double.tryParse(_secondary.text.replaceAll(',', '.'))
                : null,
          );
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    return Padding(
      padding: EdgeInsets.only(
        left: AppSpacing.xl,
        right: AppSpacing.xl,
        top: AppSpacing.xl,
        bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.xl,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            l10n.fromMap(widget.series.label, fallback: widget.series.key),
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: _value,
                  autofocus: true,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: widget.series.isPair
                        ? l10n.t('chart.systolic')
                        : l10n.t('chart.value'),
                    suffixText: widget.series.unit,
                  ),
                ),
              ),
              if (widget.series.isPair) ...<Widget>[
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: TextField(
                    controller: _secondary,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      labelText: l10n.t('chart.diastolic'),
                      suffixText: widget.series.unit,
                    ),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: AppSpacing.xl),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(l10n.t('common.save')),
          ),
        ],
      ),
    );
  }
}
