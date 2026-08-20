import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// "Mijoz qo'shish" (spec 4.2 tab 1).
///
/// As the doctor types the diagnosis, the server is asked which template it
/// matches and that template is selected immediately — it is the default state,
/// not a suggestion. The dropdown still lets the doctor override it.
class AddPatientScreen extends ConsumerStatefulWidget {
  const AddPatientScreen({super.key});

  @override
  ConsumerState<AddPatientScreen> createState() => _AddPatientScreenState();
}

class _AddPatientScreenState extends ConsumerState<AddPatientScreen> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _phoneController = TextEditingController();
  final TextEditingController _diagnosisController = TextEditingController();

  List<DiagnosisTemplate> _templates = <DiagnosisTemplate>[];
  String? _templateId;

  /// True while the selection came from auto-matching rather than the doctor.
  bool _templateAutoSelected = false;
  Timer? _matchDebounce;

  final List<ThreadDocument> _documents = <ThreadDocument>[];
  bool _busy = false;
  PatientInvite? _invite;

  @override
  void initState() {
    super.initState();
    _loadTemplates();
  }

  @override
  void dispose() {
    _matchDebounce?.cancel();
    _nameController.dispose();
    _phoneController.dispose();
    _diagnosisController.dispose();
    super.dispose();
  }

  Future<void> _loadTemplates() async {
    try {
      final List<DiagnosisTemplate> templates =
          await ref.read(threadRepositoryProvider).templates();
      if (mounted) setState(() => _templates = templates);
    } catch (_) {
      // The form still works without the dropdown; the server auto-matches.
    }
  }

  void _onDiagnosisChanged(String text) {
    _matchDebounce?.cancel();
    if (text.trim().length < 3) return;
    _matchDebounce = Timer(const Duration(milliseconds: 450), () async {
      try {
        final TemplateMatch match =
            await ref.read(threadRepositoryProvider).matchTemplate(text);
        if (!mounted || match.templateId == null) return;
        // Only overwrite while the doctor has not chosen a template by hand.
        if (_templateId == null || _templateAutoSelected) {
          setState(() {
            _templateId = match.templateId;
            _templateAutoSelected = true;
          });
        }
      } catch (_) {
        // Matching is a convenience; failing quietly is correct here.
      }
    });
  }

  Future<void> _attachDocument() async {
    final FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: <String>['pdf', 'jpg', 'jpeg', 'png'],
      allowMultiple: true,
    );
    if (result == null) return;

    setState(() => _busy = true);
    try {
      for (final PlatformFile file in result.files) {
        if (file.path == null) continue;
        final ThreadDocument document =
            await ref.read(patientRepositoryProvider).uploadDocument(
                  filePath: file.path!,
                  filename: file.name,
                );
        setState(() => _documents.add(document));
      }
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      final PatientInvite invite = await ref.read(doctorRepositoryProvider).createInvite(
            fullName: _nameController.text.trim(),
            phone: Validators.normalizePhone(_phoneController.text),
            diagnosisText: _diagnosisController.text.trim(),
            templateId: _templateId,
            documentIds: _documents.map((ThreadDocument d) => d.id).toList(),
          );
      setState(() => _invite = invite);
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _shareCode() async {
    final PatientInvite? invite = _invite;
    if (invite == null) return;
    final String text = invite.shareText ?? invite.code;
    // SMS is the reliable channel here; Telegram is a manual copy-paste.
    final Uri uri = Uri.parse(
      'sms:${invite.phone}?body=${Uri.encodeComponent(text)}',
    );
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    } else {
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) showSuccess(context, context.l10n.t('common.copied'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    if (_invite != null) return _buildCodeResult(l10n);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('doctor.add_patient_title'))),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                TextFormField(
                  controller: _nameController,
                  textCapitalization: TextCapitalization.words,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.patient_name'),
                    prefixIcon: const Icon(Icons.person_outline_rounded),
                  ),
                  validator: (String? value) => Validators.minLength(
                    value,
                    2,
                    l10n.t('error.required_field'),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextFormField(
                  controller: _phoneController,
                  keyboardType: TextInputType.phone,
                  inputFormatters: <TextInputFormatter>[
                    FilteringTextInputFormatter.allow(RegExp(r'[\d+\s()-]')),
                  ],
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.patient_phone'),
                    hintText: '+998 90 123 45 67',
                    prefixIcon: const Icon(Icons.phone_rounded),
                  ),
                  validator: (String? value) => Validators.phone(
                    value,
                    l10n.t('error.invalid_phone'),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextFormField(
                  controller: _diagnosisController,
                  maxLines: 3,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.diagnosis'),
                    alignLabelWithHint: true,
                  ),
                  onChanged: _onDiagnosisChanged,
                ),
                const SizedBox(height: AppSpacing.lg),
                DropdownButtonFormField<String>(
                  value: _templateId,
                  isExpanded: true,
                  decoration: InputDecoration(
                    labelText: l10n.t('doctor.diagnosis_template'),
                    helperText:
                        _templateAutoSelected ? l10n.t('doctor.template_auto') : null,
                    helperMaxLines: 2,
                    prefixIcon: _templateAutoSelected
                        ? const Icon(
                            Icons.auto_awesome_rounded,
                            color: AppColors.primary,
                            size: 20,
                          )
                        : null,
                  ),
                  items: _templates
                      .map(
                        (DiagnosisTemplate template) => DropdownMenuItem<String>(
                          value: template.id,
                          child: Text(l10n.fromMap(template.name)),
                        ),
                      )
                      .toList(),
                  onChanged: (String? value) => setState(() {
                    _templateId = value;
                    _templateAutoSelected = false;
                  }),
                ),
                const SizedBox(height: AppSpacing.xl),
                OutlinedButton.icon(
                  onPressed: _busy ? null : _attachDocument,
                  icon: const Icon(Icons.attach_file_rounded),
                  label: Text(l10n.t('doctor.attach_docs')),
                ),
                if (_documents.isNotEmpty) ...<Widget>[
                  const SizedBox(height: AppSpacing.md),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.sm,
                    children: _documents
                        .map(
                          (ThreadDocument document) => Chip(
                            avatar: Icon(
                              document.isPdf
                                  ? Icons.picture_as_pdf_rounded
                                  : Icons.image_rounded,
                              size: 16,
                            ),
                            label: Text(
                              document.filename,
                              overflow: TextOverflow.ellipsis,
                            ),
                            onDeleted: () => setState(() => _documents.remove(document)),
                          ),
                        )
                        .toList(),
                  ),
                ],
                const SizedBox(height: AppSpacing.xxl),
                FilledButton(
                  onPressed: _busy ? null : _save,
                  child: _busy
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2.2,
                            color: Colors.white,
                          ),
                        )
                      : Text(l10n.t('doctor.save_and_generate')),
                ),
                const SizedBox(height: AppSpacing.xl),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCodeResult(AppLocalizations l10n) {
    final PatientInvite invite = _invite!;
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.t('doctor.code_ready')),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const SizedBox(height: AppSpacing.lg),
              const Icon(
                Icons.check_circle_rounded,
                size: 56,
                color: AppColors.ok,
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                invite.fullName,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              Text(
                Formatters.phone(invite.phone),
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              if (invite.templateName != null) ...<Widget>[
                const SizedBox(height: AppSpacing.sm),
                Center(
                  child: Chip(
                    avatar: const Icon(Icons.dataset_outlined, size: 16),
                    label: Text(invite.templateName!),
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.xl),
              CodeDisplay(
                code: invite.code,
                hint: l10n.t('doctor.code_hint'),
                onShare: _shareCode,
              ),
              const Spacer(),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(l10n.t('common.done')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
