(() => {
  const palette = ["#2456d6", "#e79a25", "#26a27a"];
  const dashboardData = document.getElementById("dashboard-data");
  const comparisonData = document.getElementById("comparison-data");
  const chart = (element, rows, models) => {
    if (!element || !window.Chart) return;
    const labels = [...new Set(Object.values(models).flatMap((set) => set.map((row) => row.campaign_id)))].slice(0, 8);
    const names = new Map(Object.values(models).flatMap((set) => set.map((row) => [row.campaign_id, row.name])));
    new Chart(element, {
      type: "bar",
      data: {
        labels: labels.map((id) => names.get(id) || id),
        datasets: Object.entries(models).map(([name, set], index) => {
          const byCampaign = new Map(set.map((row) => [row.campaign_id, Number(row.attributed_revenue || 0)]));
          return { label: name.replaceAll("_", " "), data: labels.map((id) => byCampaign.get(id) || 0), backgroundColor: palette[index % palette.length], borderRadius: 4 };
        }),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } },
        scales: { x: { grid: { display: false }, ticks: { maxRotation: 25, minRotation: 0 } }, y: { beginAtZero: true, grid: { color: "#edf0f5" }, ticks: { callback: (value) => Number(value).toLocaleString() } } },
      },
    });
  };
  if (dashboardData) {
    const value = JSON.parse(dashboardData.textContent);
    chart(document.getElementById("modelChart"), value.linear, value);
  }
  if (comparisonData) {
    const value = JSON.parse(comparisonData.textContent);
    chart(document.getElementById("compareChart"), value.linear, value);
  }
})();
