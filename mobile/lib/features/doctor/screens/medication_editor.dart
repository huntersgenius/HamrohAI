import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/loading_view.dart';

/// Create or edit one prescription line (spec 4.2 tab 1).
class MedicationEditor extends ConsumerStatefulWidget {
  const MedicationEditor({
    super.key,
    required this.threadId,
    this.medication,
  });

  final String threadId;
  final Medication? medication;

  @override
  ConsumerState<MedicationEditor> createState() => _MedicationEditorState();
}

class _MedicationEditorState extends ConsumerState<MedicationEditor> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _dose;
  late final TextEditingController _instructions;
  late List<String> _times;
  bool _busy = false;

  bool get _isEdit => widget.medication != null;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.medication?.name ?? '');
    _dose = TextEditingController(text: widget.medication?.dose ?? '');
    _instructions = TextEditingController(text: widget.medication?.instructions ?? '');
    _times = List<String>.from(widget.medication?.times ?? <String>['08:00']);
  }

  @override
  void dispose() {
    _name.dispose();
    _dose.dispose();
    _instructions.dispose();
    super.dispose();
  }

  Future<void> _addTime() async {
    final TimeOfDay? picked = await showTimePicker(
      context: context,
      initialTime: const TimeOfDay(hour: 8, minute: 0),
    );
    if (picked == null) return;
    final String value =
        '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    if (_times.contains(value)) return;
    setState(() {
      _times = <String>[..._times, value]..sort();
    });
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_times.isEmpty) return;

    setState(() => _busy = true);
    try {
      final String instructions = _instructions.text.trim();
      if (_isEdit) {
        await ref.read(threadRepositoryProvider).updateMedication(
          widget.threadId,
          widget.medication!.id,
          <String, dynamic>{
            'name': _name.text.trim(),
            'dose': _dose.text.trim(),
            'times': _times,
            'instructions': instructions.isEmpty ? null : instructions,
          },
        );
      } else {
        await ref.read(threadRepositoryProvider).createMedication(
              widget.threadId,
              name: _name.text.trim(),
              dose: _dose.text.trim(),
              times: _times,
              instructions: instructions.isEmpty ? null : instructions,
            );
      }
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

    return Scaffold(
      appBar: AppBar(
        title: Text(
          _isEdit ? l10n.t('common.edit') : l10n.t('doctor.add_medication'),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                TextFormField(
                  controller: _name,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.med_name'),
                    prefixIcon: const Icon(Icons.medication_outlined),
                  ),
                  validator: (String? value) => Validators.required(
                    value,
                    l10n.t('error.required_field'),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextFormField(
                  controller: _dose,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.med_dose'),
                    hintText: '500 mg',
                  ),
                  validator: (String? value) => Validators.required(
                    value,
                    l10n.t('error.required_field'),
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
                Text(
                  l10n.t('doctor.med_times'),
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: <Widget>[
                    for (final String time in _times)
                      Chip(
                        avatar: const Icon(Icons.schedule_rounded, size: 16),
                        label: Text(time),
                        onDeleted: _times.length > 1
                            ? () => setState(
                                  () => _times =
                                      _times.where((String t) => t != time).toList(),
                                )
                            : null,
                      ),
                    ActionChip(
                      avatar: const Icon(Icons.add_rounded, size: 16),
                      label: Text(l10n.t('doctor.add_time')),
                      onPressed: _addTime,
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xl),
                TextFormField(
                  controller: _instructions,
                  maxLines: 2,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.med_instructions'),
                  ),
                ),
                const SizedBox(height: AppSpacing.xxl),
                FilledButton(
                  onPressed: _busy ? null : _save,
                  child: Text(l10n.t('common.save')),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
