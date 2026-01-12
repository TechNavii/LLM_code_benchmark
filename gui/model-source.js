(() => {
  window.__benchmarkModelSourceHelper = true;

  function initModelSource(config) {
    const sourceSelect = document.getElementById(config.modelSourceSelectId);
    const openrouterFields = document.getElementById(config.openrouterFieldsId);
    const lmstudioFields = document.getElementById(config.lmstudioFieldsId);
    const modelInput = document.getElementById(config.modelInputId);
    const providerInput = document.getElementById(config.providerInputId);
    const maxTokensInput = document.getElementById(config.maxTokensInputId);
    const lmstudioModelSelect = document.getElementById(config.lmstudioModelSelectId);
    const lmstudioModelNote = document.getElementById(config.lmstudioModelNoteId);

    if (!sourceSelect || !openrouterFields || !lmstudioFields || !lmstudioModelSelect || !modelInput) {
      return;
    }

    let openrouterModelBackup = modelInput.value || '';
    let openrouterProviderBackup = providerInput?.value || '';
    let openrouterMaxTokensBackup = maxTokensInput?.value || '';
    let inFlight = null;
    let activeLmStudioModel = '';

    async function switchLmStudioModel(modelId) {
      if (!modelId) return;

      lmstudioModelSelect.disabled = true;
      setLmStudioNote(`Loading '${modelId}' in LM Studio…`);

      try {
        const response = await fetch('/models/lmstudio/switch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_id: modelId })
        });

        if (!response.ok) {
          let detail = '';
          try {
            const payload = await response.json();
            detail = payload?.detail || '';
          } catch {
            // ignore
          }
          throw new Error(detail || response.statusText || 'Unable to switch LM Studio model');
        }

        activeLmStudioModel = modelId;
      } catch (error) {
        setLmStudioNote(error?.message || 'Unable to switch LM Studio model.');
        return;
      } finally {
        lmstudioModelSelect.disabled = false;
      }

      applyLmStudioModelSelection();
    }

    function getSource() {
      return sourceSelect.value === 'lmstudio' ? 'lmstudio' : 'openrouter';
    }

    function setLmStudioNote(text) {
      if (lmstudioModelNote) lmstudioModelNote.textContent = text || '';
    }

    function applyLmStudioModelSelection() {
      if (getSource() !== 'lmstudio') return;

      const selected = lmstudioModelSelect.value;
      if (!selected) {
        modelInput.value = '';
        setLmStudioNote('Select a model to continue.');
        return;
      }

      modelInput.value = `lmstudio/${selected}`;

      const contextRaw = lmstudioModelSelect.selectedOptions?.[0]?.dataset?.context;
      const context = contextRaw ? parseInt(contextRaw, 10) : NaN;
      if (maxTokensInput && Number.isFinite(context) && context > 0) {
        maxTokensInput.value = String(context);
        maxTokensInput.max = String(context);
      } else if (maxTokensInput) {
        maxTokensInput.removeAttribute('max');
      }

      setLmStudioNote(
        Number.isFinite(context) && context > 0
          ? `Context: ${context} tokens`
          : 'Context: unknown (adjust max tokens manually)'
      );
    }

    async function loadLmStudioModels() {
      if (inFlight) return inFlight;

      lmstudioModelSelect.disabled = true;
      lmstudioModelSelect.innerHTML = '';
      const loading = document.createElement('option');
      loading.value = '';
      loading.textContent = 'Loading…';
      lmstudioModelSelect.appendChild(loading);
      setLmStudioNote('Loading models from LM Studio…');

      inFlight = fetch('/models/lmstudio')
        .then(async (response) => {
          if (!response.ok) {
            let detail = '';
            try {
              const payload = await response.json();
              detail = payload?.detail || '';
            } catch {
              // ignore
            }
            throw new Error(detail || response.statusText || 'Unable to load models');
          }
          return response.json();
        })
        .then((data) => {
          const models = Array.isArray(data?.models) ? data.models : [];
          lmstudioModelSelect.innerHTML = '';
          if (!models.length) {
            const empty = document.createElement('option');
            empty.value = '';
            empty.textContent = 'No models found';
            lmstudioModelSelect.appendChild(empty);
            setLmStudioNote('No LM Studio models were returned.');
            return;
          }

          models.forEach((entry) => {
            if (!entry?.id) return;
            const option = document.createElement('option');
            option.value = entry.id;
            option.textContent = entry.id;
            if (entry.context_length) option.dataset.context = String(entry.context_length);
            lmstudioModelSelect.appendChild(option);
          });

          lmstudioModelSelect.disabled = false;
          applyLmStudioModelSelection();
          activeLmStudioModel = lmstudioModelSelect.value;
        })
        .catch((error) => {
          lmstudioModelSelect.innerHTML = '';
          const failed = document.createElement('option');
          failed.value = '';
          failed.textContent = 'Unable to connect';
          lmstudioModelSelect.appendChild(failed);
          setLmStudioNote(error?.message || 'Unable to load LM Studio models.');
        })
        .finally(() => {
          inFlight = null;
        });

      return inFlight;
    }

    async function handleLmStudioModelChange() {
      const selected = lmstudioModelSelect.value;
      applyLmStudioModelSelection();

      if (getSource() !== 'lmstudio') return;
      if (!selected) {
        activeLmStudioModel = '';
        return;
      }

      if (selected === activeLmStudioModel) return;
      await switchLmStudioModel(selected);
    }

    function applyModelSourceUI() {
      const isLmstudio = getSource() === 'lmstudio';
      openrouterFields.hidden = isLmstudio;
      lmstudioFields.hidden = !isLmstudio;

      if (isLmstudio) {
        if (!modelInput.disabled) {
          openrouterModelBackup = modelInput.value || '';
          if (providerInput) openrouterProviderBackup = providerInput.value || '';
          if (maxTokensInput) openrouterMaxTokensBackup = maxTokensInput.value || '';
        }

        modelInput.disabled = true;
        modelInput.required = false;
        modelInput.value = '';

        if (providerInput) {
          providerInput.value = '';
          providerInput.disabled = true;
        }

        loadLmStudioModels();
        return;
      }

      modelInput.disabled = false;
      modelInput.required = true;
      if (openrouterModelBackup) modelInput.value = openrouterModelBackup;

      if (providerInput) {
        providerInput.disabled = false;
        providerInput.value = openrouterProviderBackup;
      }

      if (maxTokensInput) {
        if (openrouterMaxTokensBackup && openrouterMaxTokensBackup.trim()) {
          maxTokensInput.value = openrouterMaxTokensBackup;
        }
        maxTokensInput.removeAttribute('max');
      }

      setLmStudioNote('');
    }

    sourceSelect.addEventListener('change', applyModelSourceUI);
    sourceSelect.addEventListener('input', applyModelSourceUI);
    lmstudioModelSelect.addEventListener('change', handleLmStudioModelChange);
    applyModelSourceUI();
  }

  const configs = [
    {
      modelSourceSelectId: 'model-source-select',
      openrouterFieldsId: 'openrouter-fields',
      lmstudioFieldsId: 'lmstudio-fields',
      modelInputId: 'model-input',
      providerInputId: 'provider-input',
      maxTokensInputId: 'max-tokens-input',
      lmstudioModelSelectId: 'lmstudio-model-select',
      lmstudioModelNoteId: 'lmstudio-model-note',
    },
    {
      modelSourceSelectId: 'qa-model-source-select',
      openrouterFieldsId: 'qa-openrouter-fields',
      lmstudioFieldsId: 'qa-lmstudio-fields',
      modelInputId: 'qa-model-input',
      providerInputId: 'qa-provider-input',
      maxTokensInputId: 'qa-max-tokens-input',
      lmstudioModelSelectId: 'qa-lmstudio-model-select',
      lmstudioModelNoteId: 'qa-lmstudio-model-note',
    },
  ];

  configs.forEach(initModelSource);
})();
