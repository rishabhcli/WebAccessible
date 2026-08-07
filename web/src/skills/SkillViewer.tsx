import { useEffect, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  BookOpenText,
  CalendarClock,
  FileText,
  Pencil,
  RefreshCw,
  Save,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { SkillDocument } from "../api/types";

interface SkillViewerProps {
  skillId: string;
  onClose: () => void;
  editable?: boolean;
  onChanged?: (skill: SkillDocument) => void;
  onDeleted?: () => void;
}

type EditorMode = "read" | "edit" | "delete";

export function SkillViewer({
  skillId,
  onClose,
  editable = false,
  onChanged,
  onDeleted,
}: SkillViewerProps) {
  const [skill, setSkill] = useState<SkillDocument>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [operationError, setOperationError] = useState<string>();
  const [mode, setMode] = useState<EditorMode>("read");
  const [draftName, setDraftName] = useState("");
  const [draftInstructions, setDraftInstructions] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const loaded = await api.getSkill(skillId);
      setSkill(loaded);
      resetDraft(loaded);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "This routine could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  const resetDraft = (document: SkillDocument) => {
    setDraftName(document.name);
    setDraftInstructions(Object.fromEntries(document.steps.map((step) => [step.id, step.instruction])));
    setReason("");
    setOperationError(undefined);
  };

  useEffect(() => {
    void load();
  }, [skillId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const changedInstructions = skill?.steps.filter(
    (step) => (draftInstructions[step.id] ?? "").trim() !== step.instruction,
  ) ?? [];
  const nameChanged = Boolean(skill && draftName.trim() !== skill.name);
  const hasChanges = nameChanged || changedInstructions.length > 0;

  const saveRevision = async (event: FormEvent) => {
    event.preventDefault();
    if (!skill?.revision || !hasChanges || !reason.trim()) return;
    setSaving(true);
    setOperationError(undefined);
    try {
      const saved = await api.reviseSkill(skill.id, {
        expected_revision: skill.revision,
        name: nameChanged ? draftName.trim() : undefined,
        instruction_edits: changedInstructions.map((step) => ({
          step_id: step.id,
          instruction: (draftInstructions[step.id] ?? step.instruction).trim(),
        })),
        reason: reason.trim(),
      });
      setSkill(saved);
      resetDraft(saved);
      setMode("read");
      onChanged?.(saved);
    } catch (failure) {
      setOperationError(
        failure instanceof Error ? failure.message : "EverOS could not save this revision.",
      );
    } finally {
      setSaving(false);
    }
  };

  const deleteRoutine = async () => {
    if (!skill) return;
    setDeleting(true);
    setOperationError(undefined);
    try {
      await api.deleteSkill(skill.id);
      onDeleted?.();
      onClose();
    } catch (failure) {
      setOperationError(
        failure instanceof Error ? failure.message : "EverOS could not delete this routine.",
      );
    } finally {
      setDeleting(false);
    }
  };

  const cancelOperation = () => {
    if (skill) resetDraft(skill);
    setMode("read");
  };

  return (
    <div aria-labelledby="skill-title" aria-modal="true" className="modal-backdrop" role="dialog">
      <section className="skill-dialog">
        <header className="dialog-header">
          <div>
            <span className="section-kicker"><BookOpenText aria-hidden="true" size={19} /> Saved routine</span>
            <h2 id="skill-title">{skill?.name ?? "Routine details"}</h2>
          </div>
          <div className="dialog-header__actions">
            {editable && skill && mode === "read" ? (
              <>
                <button aria-label="Edit routine" className="icon-button" onClick={() => setMode("edit")} title="Edit routine" type="button"><Pencil aria-hidden="true" size={21} /></button>
                <button aria-label="Delete routine" className="icon-button icon-button--danger" onClick={() => setMode("delete")} title="Delete routine" type="button"><Trash2 aria-hidden="true" size={21} /></button>
              </>
            ) : null}
            <button aria-label="Close routine details" className="icon-button" onClick={onClose} title="Close" type="button"><X aria-hidden="true" size={24} /></button>
          </div>
        </header>

        {loading ? <div className="loading-line" role="status"><span className="spinner" /> Loading routine</div> : null}
        {error ? (
          <div className="dialog-error" role="alert">
            <p>{error}</p>
            <button className="button button--secondary" onClick={() => void load()} type="button"><RefreshCw aria-hidden="true" size={19} /> Try again</button>
          </div>
        ) : null}
        {skill ? (
          <>
            <dl className="skill-meta">
              <div><dt>Revision</dt><dd>{skill.revision ?? "Not reported"}</dd></div>
              <div><dt>Outcome</dt><dd>{skill.outcome ?? "Not reported"}</dd></div>
              <div><dt><CalendarClock aria-hidden="true" size={17} /> Updated</dt><dd>{skill.updatedAt ? new Date(skill.updatedAt).toLocaleString() : "Not reported"}</dd></div>
            </dl>

            {mode === "edit" ? (
              <form className="skill-editor" onSubmit={saveRevision}>
                <label className="field">
                  <span>Routine name</span>
                  <input maxLength={160} onChange={(event) => setDraftName(event.target.value)} required value={draftName} />
                </label>
                <fieldset className="fieldset-reset skill-editor__steps">
                  <legend>Guidance instructions</legend>
                  {skill.steps.map((step, index) => (
                    <label className="field" key={step.id}>
                      <span>Step {index + 1}</span>
                      <textarea
                        maxLength={240}
                        onChange={(event) => setDraftInstructions((current) => ({ ...current, [step.id]: event.target.value }))}
                        required
                        rows={2}
                        value={draftInstructions[step.id] ?? ""}
                      />
                    </label>
                  ))}
                </fieldset>
                <label className="field">
                  <span>Reason for this revision</span>
                  <input maxLength={160} onChange={(event) => setReason(event.target.value)} placeholder="What changed?" required value={reason} />
                </label>
                {operationError ? <p className="form-error" role="alert">{operationError}</p> : null}
                <div className="skill-editor__actions">
                  <button className="button button--quiet" onClick={cancelOperation} type="button"><Undo2 aria-hidden="true" size={19} /> Cancel</button>
                  <button className="button button--primary" disabled={saving || !hasChanges || !reason.trim() || !skill.revision} type="submit"><Save aria-hidden="true" size={19} /> {saving ? "Saving" : "Save revision"}</button>
                </div>
              </form>
            ) : (
              <div className="skill-document">
                {mode === "delete" ? (
                  <div className="skill-delete">
                    <AlertTriangle aria-hidden="true" size={24} />
                    <div><strong>Delete this routine from EverOS?</strong><p>Only this skill may be deleted. Broader participant memory will not be removed.</p></div>
                    <div className="skill-delete__actions">
                      <button className="button button--quiet" onClick={cancelOperation} type="button">Cancel</button>
                      <button className="button button--danger" disabled={deleting} onClick={() => void deleteRoutine()} type="button"><Trash2 aria-hidden="true" size={19} /> {deleting ? "Deleting" : "Delete routine"}</button>
                    </div>
                    {operationError ? <p className="form-error" role="alert">{operationError}</p> : null}
                  </div>
                ) : null}
                <div className="skill-document__bar"><FileText aria-hidden="true" size={18} /> EverOS skill document</div>
                <pre>{skill.markdown}</pre>
              </div>
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}
