const state = { user: null, workouts: [], meals: [], progress: [], stats: null, page: "dashboard", authMode: "login", workoutFilter: "All" };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeText = (value) => String(value ?? "");

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  let payload;
  try { payload = await response.json(); } catch { throw new Error("The server returned an unexpected response."); }
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/login" && path !== "/api/signup") showAuth();
    throw new Error(payload.error || "Something went wrong. Please try again.");
  }
  return payload;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

function showAuth() {
  $("#authScreen").classList.remove("hidden");
  $("#appShell").classList.add("hidden");
  state.user = null;
}

function showApp(user) {
  state.user = user;
  $("#authScreen").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
  $("#sidebarName").textContent = user.name;
  $("#userAvatar").textContent = user.name.charAt(0).toUpperCase();
  $("#topAvatar").textContent = user.name.charAt(0).toUpperCase();
  $("#welcomeTitle").innerHTML = `Good to see you, <span id="welcomeName"></span> <span class="wave">✳</span>`;
  $("#welcomeName").textContent = user.name.split(/\s+/)[0];
  $("#dashboardGoal").textContent = user.goal;
  $("#todayLabel").textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date());
  renderProfile();
  setPage(state.page);
}

function renderProfile() {
  const user = state.user;
  if (!user) return;
  $("#profileAvatar").textContent = user.name.charAt(0).toUpperCase();
  $("#profileDisplayName").textContent = user.name;
  $("#profileDisplayEmail").textContent = user.email;
  $("#profileDisplayGoal").textContent = user.goal;
  $("#profileDisplayLevel").textContent = user.level;
  const form = $("#profileForm");
  for (const key of ["name", "email", "age", "gender", "height_cm", "weight_kg", "goal", "level"]) {
    form.elements[key].value = user[key] ?? "";
  }
}

function setPage(page) {
  if (!["dashboard", "workouts", "nutrition", "progress", "profile"].includes(page)) return;
  state.page = page;
  $$(".page").forEach((section) => section.classList.toggle("active", section.id === `${page}Page`));
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  $("#breadcrumbPage").textContent = ({ dashboard: "Overview", workouts: "Workouts", nutrition: "Nutrition", progress: "My progress", profile: "My profile" })[page];
  $("#appShell").classList.remove("menu-open");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function workoutCard(workout) {
  const card = document.createElement("article");
  card.className = "workout-card";
  card.innerHTML = `<div class="workout-visual"><span aria-hidden="true">${workout.icon}</span><span class="level-badge">${workout.level}</span></div>
    <div class="workout-body"><span class="workout-tag">${workout.category.toUpperCase()}</span><h2></h2><p></p>
    <div class="workout-meta"><span>◷ ${workout.duration} minutes</span><span>${workout.days}</span></div>
    <button class="button button-primary" type="button">Add to my progress <span>↗</span></button></div>`;
  $("h2", card).textContent = workout.name;
  $("p", card).textContent = workout.description;
  $(".button", card).addEventListener("click", () => {
    setPage("progress");
    $("#progressForm").elements.workout.value = workout.name;
    $("#progressForm").elements.minutes.value = workout.duration;
    $("#progressForm").elements.workout.focus();
  });
  return card;
}

function renderWorkouts() {
  const grid = $("#workoutGrid");
  grid.replaceChildren();
  state.workouts.filter((item) => state.workoutFilter === "All" || item.category === state.workoutFilter).forEach((item) => grid.append(workoutCard(item)));
}

function renderMeals() {
  const grid = $("#mealGrid");
  grid.replaceChildren();
  state.meals.forEach((meal) => {
    const card = document.createElement("article");
    card.className = "meal-card";
    card.innerHTML = `<div class="meal-symbol" aria-hidden="true">${meal.icon}</div><div class="meal-copy"><span class="eyebrow"></span><h3></h3><p></p></div><span class="meal-calories">${meal.calories} cal*</span>`;
    $(".eyebrow", card).textContent = meal.time;
    $("h3", card).textContent = meal.name;
    $("p", card).textContent = meal.items;
    grid.append(card);
  });
}

function renderDashboard() {
  if (!state.stats) return;
  $("#weekWorkouts").textContent = state.stats.workouts_this_week;
  $("#weekMinutes").textContent = state.stats.minutes_this_week;
  $("#minutesProgress").style.width = `${Math.min(100, Math.round(state.stats.minutes_this_week / 150 * 100))}%`;
  const weekDots = $("#weekDots");
  weekDots.replaceChildren();
  for (let day = 0; day < 7; day += 1) {
    const item = document.createElement("span");
    const completed = state.progress.some((entry) => {
      const date = new Date(`${entry.entry_date}T12:00:00`);
      const monday = new Date();
      monday.setHours(12, 0, 0, 0);
      monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
      const target = new Date(monday);
      target.setDate(target.getDate() + day);
      return date.toDateString() === target.toDateString();
    });
    item.className = `week-dot${completed ? " done" : ""}`;
    item.textContent = ["M", "T", "W", "T", "F", "S", "S"][day];
    weekDots.append(item);
  }
  const workout = state.workouts[0];
  if (workout) {
    const featured = $("#featuredWorkout");
    featured.innerHTML = `<div class="workout-symbol">${workout.icon}</div><div class="featured-copy"><h3></h3><p></p><span class="tiny-meta">${workout.duration} min · ${workout.level}</span></div>`;
    $("h3", featured).textContent = workout.name;
    $("p", featured).textContent = workout.description;
    featured.onclick = () => setPage("workouts");
    featured.style.cursor = "pointer";
  }
  const meal = state.meals[0];
  if (meal) {
    const featured = $("#featuredMeal");
    featured.innerHTML = `<div class="meal-symbol">${meal.icon}</div><div class="meal-copy"><span class="eyebrow"></span><h3></h3><p></p></div>`;
    $(".eyebrow", featured).textContent = meal.time;
    $("h3", featured).textContent = meal.name;
    $("p", featured).textContent = meal.items;
    featured.onclick = () => setPage("nutrition");
    featured.style.cursor = "pointer";
  }
  renderHistory();
}

function renderHistory() {
  const list = $("#progressHistory");
  list.replaceChildren();
  $("#historyCount").textContent = `${state.progress.length} ${state.progress.length === 1 ? "session" : "sessions"}`;
  if (!state.progress.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Your story starts with one small step. Log a session and it'll show up here.";
    list.append(empty);
    return;
  }
  state.progress.forEach((entry) => {
    const row = document.createElement("article");
    row.className = "history-item";
    const date = new Date(`${entry.entry_date}T12:00:00`);
    const dateLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
    row.innerHTML = `<div class="history-date-icon">↗</div><div><h3></h3><p></p></div><span class="history-minutes"></span>`;
    $("h3", row).textContent = entry.workout;
    $("p", row).textContent = `${dateLabel}${entry.note ? ` · ${entry.note}` : ""}`;
    $(".history-minutes", row).textContent = `${entry.minutes} min`;
    list.append(row);
  });
}

async function refreshDashboard() {
  const [dashboard, plans] = await Promise.all([api("/api/dashboard"), api("/api/plans")]);
  state.user = dashboard.user;
  state.progress = dashboard.progress;
  state.stats = dashboard.stats;
  state.workouts = plans.workouts;
  state.meals = plans.meals;
  showApp(state.user);
  renderDashboard();
  renderWorkouts();
  renderMeals();
}

function setAuthMode(mode) {
  state.authMode = mode;
  const signup = mode === "signup";
  $$(".auth-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.authMode === mode));
  $("#signupFields").classList.toggle("hidden", !signup);
  $("#authTitle").textContent = signup ? "Let's make this yours." : "Make yourself at home.";
  $("#authSubtitle").textContent = signup ? "A few details, then we can get started." : "Sign in to pick up right where you left off.";
  $("#authSubmit").innerHTML = signup ? "Create my account <span>↗</span>" : "Sign in <span>↗</span>";
  $("#authForm").elements.password.autocomplete = signup ? "new-password" : "current-password";
  $("#authError").textContent = "";
}

$("#authForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const payload = Object.fromEntries(values.entries());
  $("#authError").textContent = "";
  $("#authSubmit").disabled = true;
  try {
    const result = await api(state.authMode === "signup" ? "/api/signup" : "/api/login", { method: "POST", body: JSON.stringify(payload) });
    await refreshDashboard();
    showToast(state.authMode === "signup" ? `Welcome to FitLife, ${result.user.name.split(/\s+/)[0]}!` : "Welcome back. It's good to see you.");
  } catch (error) {
    $("#authError").textContent = error.message;
  } finally {
    $("#authSubmit").disabled = false;
  }
});

$$(".auth-tab").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.authMode)));
$$("[data-page]").forEach((button) => button.addEventListener("click", () => {
  const page = button.dataset.page;
  if (page) setPage(page);
}));
$("#logoutButton").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
    showAuth();
    setAuthMode("login");
    $("#authForm").reset();
    showToast("You have been signed out. Take care!");
  } catch (error) { showToast(error.message); }
});
$("#mobileMenu").addEventListener("click", () => $("#appShell").classList.toggle("menu-open"));
$("#mobileOverlay").addEventListener("click", () => $("#appShell").classList.remove("menu-open"));
$$(".filter-pill").forEach((button) => button.addEventListener("click", () => {
  state.workoutFilter = button.dataset.filter;
  $$(".filter-pill").forEach((pill) => pill.classList.toggle("active", pill === button));
  renderWorkouts();
}));

$("#progressForm").elements.entry_date.value = new Date().toISOString().slice(0, 10);
$("#progressForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    await api("/api/progress", { method: "POST", body: JSON.stringify(values) });
    event.currentTarget.reset();
    event.currentTarget.elements.entry_date.value = new Date().toISOString().slice(0, 10);
    await refreshDashboard();
    setPage("progress");
    showToast("Session saved. That's another little win!");
  } catch (error) { showToast(error.message); }
});

$("#profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    const result = await api("/api/profile", { method: "PUT", body: JSON.stringify(values) });
    state.user = result.user;
    showApp(result.user);
    showToast("Your details are all up to date.");
  } catch (error) { showToast(error.message); }
});

async function start() {
  try {
    const user = await api("/api/me");
    await refreshDashboard();
  } catch (error) {
    showAuth();
    if (!error.message.includes("sign in")) $("#authError").textContent = error.message;
  }
}

start();
