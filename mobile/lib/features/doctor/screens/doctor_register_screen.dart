import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/loading_view.dart';

/// Doctor registration form (spec 4.1).
///
/// Submitting creates the profile in "tekshiruv kutilmoqda". Approval happens
/// manually in the database during the MVP, so there is no approval UI here.
class DoctorRegisterScreen extends ConsumerStatefulWidget {
  const DoctorRegisterScreen({super.key});

  @override
  ConsumerState<DoctorRegisterScreen> createState() => _DoctorRegisterScreenState();
}

class _DoctorRegisterScreenState extends ConsumerState<DoctorRegisterScreen> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _ageController = TextEditingController();
  final TextEditingController _experienceController = TextEditingController();
  final TextEditingController _workplaceController = TextEditingController();
  final TextEditingController _bioController = TextEditingController();

  String? _specialty;
  String? _documentId;
  String? _documentName;
  bool _busy = false;

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    _experienceController.dispose();
    _workplaceController.dispose();
    _bioController.dispose();
    super.dispose();
  }

  Future<void> _pickDocument() async {
    final FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: <String>['pdf', 'jpg', 'jpeg', 'png'],
    );
    final String? path = result?.files.single.path;
    if (path == null) return;

    setState(() => _busy = true);
    try {
      final ThreadDocument document =
          await ref.read(patientRepositoryProvider).uploadDocument(
                filePath: path,
                filename: result!.files.single.name,
                purpose: 'doctor_license',
              );
      setState(() {
        _documentId = document.id;
        _documentName = document.filename;
      });
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    final AppLocalizations l10n = context.l10n;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_specialty == null || _documentId == null) {
      showApiError(context, l10n.t('error.validation'));
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(doctorRepositoryProvider).register(
            fullName: _nameController.text.trim(),
            specialty: _specialty!,
            experienceYears: int.parse(_experienceController.text.trim()),
            licenseDocumentId: _documentId!,
            age: int.tryParse(_ageController.text.trim()),
            bio: _bioController.text.trim().isEmpty ? null : _bioController.text.trim(),
            workplace: _workplaceController.text.trim().isEmpty
                ? null
                : _workplaceController.text.trim(),
          );
      await ref.read(sessionProvider.notifier).refresh();
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);
    final AsyncValue<List<SpecialtyOption>> specialties = ref.watch(specialtiesProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('doctor.register_title'))),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Text(
                  l10n.t('doctor.register_subtitle'),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
                TextFormField(
                  controller: _nameController,
                  textCapitalization: TextCapitalization.words,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.full_name'),
                  ),
                  validator: (String? value) => Validators.minLength(
                    value,
                    2,
                    l10n.t('error.required_field'),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: TextFormField(
                        controller: _ageController,
                        keyboardType: TextInputType.number,
                        inputFormatters: <TextInputFormatter>[
                          FilteringTextInputFormatter.digitsOnly,
                        ],
                        decoration: InputDecoration(
                          labelText: l10n.t('doctor.age'),
                        ),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: TextFormField(
                        controller: _experienceController,
                        keyboardType: TextInputType.number,
                        inputFormatters: <TextInputFormatter>[
                          FilteringTextInputFormatter.digitsOnly,
                        ],
                        decoration: InputDecoration(
                          labelText: l10n.t('doctor.experience'),
                        ),
                        validator: (String? value) => Validators.positiveInt(
                          value,
                          l10n.t('error.required_field'),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.lg),
                specialties.when(
                  data: (List<SpecialtyOption> options) =>
                      DropdownButtonFormField<String>(
                    value: _specialty,
                    isExpanded: true,
                    decoration: InputDecoration(
                      labelText: l10n.t('doctor.specialty'),
                    ),
                    items: options
                        .map(
                          (SpecialtyOption option) => DropdownMenuItem<String>(
                            value: option.code,
                            child: Text(l10n.fromMap(option.name)),
                          ),
                        )
                        .toList(),
                    onChanged: (String? value) => setState(() => _specialty = value),
                    validator: (String? value) =>
                        value == null ? l10n.t('error.required_field') : null,
                  ),
                  loading: () => const LinearProgressIndicator(minHeight: 2),
                  error: (Object error, StackTrace _) => Text(l10n.t('common.error')),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextFormField(
                  controller: _workplaceController,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.workplace'),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextFormField(
                  controller: _bioController,
                  maxLines: 3,
                  decoration: InputDecoration(labelText: l10n.t('doctor.bio')),
                ),
                const SizedBox(height: AppSpacing.xl),
                Text(
                  l10n.t('doctor.license'),
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                OutlinedButton.icon(
                  onPressed: _busy ? null : _pickDocument,
                  icon: Icon(
                    _documentId == null
                        ? Icons.upload_file_rounded
                        : Icons.check_circle_rounded,
                    color: _documentId == null ? null : AppColors.ok,
                  ),
                  label: Text(
                    _documentName ?? l10n.t('doctor.pick_file'),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(height: AppSpacing.xxl),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2.2,
                            color: Colors.white,
                          ),
                        )
                      : Text(l10n.t('doctor.submit')),
                ),
                const SizedBox(height: AppSpacing.xl),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Shown while the licence is under manual review.
class DoctorPendingScreen extends ConsumerWidget {
  const DoctorPendingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    return Scaffold(
      body: SafeArea(
        child: EmptyView(
          icon: Icons.hourglass_top_rounded,
          title: l10n.t('doctor.pending_title'),
          message: l10n.t('doctor.pending_body'),
          action: OutlinedButton.icon(
            onPressed: () {
              ref.invalidate(doctorProfileProvider);
              ref.read(sessionProvider.notifier).refresh();
            },
            icon: const Icon(Icons.refresh_rounded),
            label: Text(l10n.t('common.retry')),
          ),
        ),
      ),
    );
  }
}
