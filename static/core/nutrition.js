document.addEventListener("DOMContentLoaded", function () {
  const dataElement = document.getElementById("food-nutrition-data");
  const form = document.getElementById("food-serving-form");
  if (!dataElement || !form) return;

  const data = JSON.parse(dataElement.textContent);
  const optionSelect = document.getElementById("serving-option");
  const countWrap = document.getElementById("serving-count-wrap");
  const countInput = document.getElementById("serving-count");
  const gramsWrap = document.getElementById("custom-grams-wrap");
  const gramsInput = document.getElementById("custom-grams");
  const weightOutput = document.getElementById("selected-weight");
  const units = {
    calories: "kcal",
    protein_g: "g",
    carbs_g: "g",
    fat_g: "g",
    fiber_g: "g",
    sugar_g: "g",
    sodium_mg: "mg",
  };

  function selectedWeight() {
    if (optionSelect.value === "custom") {
      return Number(gramsInput.value);
    }
    const option = data.servings.find(function (serving) {
      return String(serving.index) === optionSelect.value;
    });
    const count = Number(countInput.value);
    return option && Number.isFinite(count) ? Number(option.weight_g) * count : NaN;
  }

  function updatePreview() {
    const weight = selectedWeight();
    const validWeight = Number.isFinite(weight) && weight > 0;
    weightOutput.textContent = validWeight
      ? "Selected weight: " + weight.toFixed(1) + " g"
      : "Enter a valid serving weight.";

    Object.keys(units).forEach(function (key) {
      const output = document.querySelector('[data-nutrient="' + key + '"]');
      const per100g = Number(data.per_100g[key]);
      output.textContent = validWeight && Number.isFinite(per100g)
        ? ((per100g * weight) / 100).toFixed(2) + " " + units[key]
        : "—";
    });
  }

  function updateServingControls() {
    const custom = optionSelect.value === "custom";
    countWrap.hidden = custom;
    countInput.disabled = custom;
    gramsWrap.hidden = !custom;
    gramsInput.disabled = !custom;
    gramsInput.required = custom;
    updatePreview();
  }

  optionSelect.addEventListener("change", updateServingControls);
  countInput.addEventListener("input", updatePreview);
  gramsInput.addEventListener("input", updatePreview);
  updateServingControls();
});
