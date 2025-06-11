from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
from models import db, GradeLevel, Group, Subject, User, Attendance, Behavior
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, time, timezone
import os

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'supersecretkey'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        # Crear tablas si no existen
        db.create_all()

        # Crear datos de ejemplo si no existen
        if not GradeLevel.query.first():
            grade = GradeLevel(name="1er Grado", description="Ejemplo")
            db.session.add(grade)
            db.session.commit()
        if not Group.query.first():
            group = Group(name="Grupo A", description="Ejemplo")
            db.session.add(group)
            db.session.commit()
        if not Subject.query.first():
            subject = Subject(name="Matemáticas", description="Ejemplo")
            db.session.add(subject)
            db.session.commit()
        # Crear usuario admin por defecto si no existe
        if not User.query.filter_by(is_admin=True).first():
            admin = User(
                username="admin",
                password_hash=generate_password_hash("admin123"),
                first_name="Admin",
                last_name="Principal",
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Usuario admin creado con contraseña por defecto: admin123")

    return app


app = create_app()


@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = User.query.get(user_id)
        if g.user:
            g.user.last_activity_at = datetime.utcnow()
            db.session.commit()

@app.context_processor
def inject_globals():
    now_aware = datetime.now(timezone.utc)
    return dict(current_user=g.user, current_year=now_aware.year, now=lambda: now_aware)

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/about")
def about():
    abort(404)


@app.route("/register", methods=["GET", "POST"])
def register():
    from models import GradeLevel, Group
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form["confirm"]
        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        grade_level_id = request.form.get("grade_level")
        group_id = request.form.get("group")
        if not (username and password and confirm and first_name and last_name and grade_level_id):
            flash("Todos los campos obligatorios deben ser completados.", "warning")
        elif password != confirm:
            flash("Las contraseñas no coinciden.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("El nombre de usuario ya existe.", "danger")
        else:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                is_admin=False,
                grade_level_id=grade_level_id,
                group_id=group_id if group_id else None,
                first_name=first_name,
                last_name=last_name
            )
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["user_id"] = user.id
            flash("Registro exitoso. Bienvenido.", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html", grade_levels=grade_levels, groups=groups)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            flash("Sesión iniciada correctamente.", "success")
            # Redirigir según el tipo de usuario
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("dashboard"))
        else:
            flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("login"))

def login_required(view):
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("Debes iniciar sesión.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped_view.__name__ = view.__name__
    return wrapped_view

@app.route("/dashboard")
@login_required
def dashboard():
    if g.user.is_admin:
        return redirect(url_for("admin_dashboard"))
    tasks = g.user.tasks
    schedule = g.user.class_schedules
    grades = g.user.grades.all()  # <-- Usa .all() si la relación es lazy='dynamic'
    subject_ids = set([g.subject_id for g in grades])
    subject_ids.update([ss.subject_id for ss in g.user.student_subjects])
    subjects = Subject.query.filter(Subject.id.in_(subject_ids)).all() if subject_ids else []
    return render_template(
        "dashboard.html",
        tasks=tasks,
        schedule=schedule,
        grades=grades,
        subjects=subjects
    )

def admin_required(view):
    def wrapped_view(*args, **kwargs):
        if g.user is None or not g.user.is_admin:
            flash("Acceso solo para administradores.", "danger")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped_view.__name__ = view.__name__
    return wrapped_view

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    total_estudiantes = User.query.filter_by(is_admin=False).count()
    total_grupos = Group.query.count()
    total_materias = Subject.query.count()
    total_grados = GradeLevel.query.count()
    return render_template(
        "admin_dashboard.html",
        total_estudiantes=total_estudiantes,
        total_grupos=total_grupos,
        total_materias=total_materias,
        total_grados=total_grados
    )

@app.route("/admin/users")
@admin_required
def admin_users():
    grade_level_id = request.args.get("grade_level")
    group_id = request.args.get("group")
    query = User.query.filter_by(is_admin=False)
    if grade_level_id:
        query = query.filter_by(grade_level_id=grade_level_id)
    if group_id:
        query = query.filter_by(group_id=group_id)
    users = query.all()
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    return render_template(
        "admin_users.html",
        users=users,
        grade_levels=grade_levels,
        groups=groups,
        selected_grade=grade_level_id,
        selected_group=group_id
    )

@app.route("/admin/users/add", methods=["GET", "POST"])
@admin_required
def admin_add_user():
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form["confirm"]
        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        grade_level_id = request.form.get("grade_level")
        group_id = request.form.get("group")
        is_admin = bool(request.form.get("is_admin"))

        if not (username and password and confirm and first_name and last_name and grade_level_id):
            flash("Todos los campos obligatorios deben ser completados.", "warning")
        elif password != confirm:
            flash("Las contraseñas no coinciden.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("El nombre de usuario ya existe.", "danger")
        else:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                first_name=first_name,
                last_name=last_name,
                is_admin=is_admin,
                grade_level_id=grade_level_id,
                group_id=group_id if group_id else None
            )
            db.session.add(user)
            db.session.commit()
            flash("Usuario creado correctamente.", "success")
            return redirect(url_for("admin_users"))
    return render_template("admin_add_user.html", grade_levels=grade_levels, groups=groups)

@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    if request.method == "POST":
        user.first_name = request.form["first_name"]
        user.last_name = request.form["last_name"]
        user.grade_level_id = request.form.get("grade_level")
        user.group_id = request.form.get("group")
        is_admin = bool(request.form.get("is_admin"))
        user.is_admin = is_admin
        if request.form.get("password"):
            user.password_hash = generate_password_hash(request.form["password"])
        db.session.commit()
        flash("Usuario actualizado correctamente.", "success")
        return redirect(url_for("admin_users"))
    return render_template("admin_edit_user.html", user=user, grade_levels=grade_levels, groups=groups)

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("Usuario eliminado correctamente.", "info")
    return redirect(url_for("admin_users"))

@app.route("/admin/groups")
@admin_required
def admin_groups():
    groups = Group.query.all()
    return render_template("admin_groups.html", groups=groups)

@app.route("/admin/groups/add", methods=["GET", "POST"])
@admin_required
def admin_add_group():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        if not name:
            flash("El nombre es obligatorio.", "warning")
        elif Group.query.filter_by(name=name).first():
            flash("Ya existe un grupo con ese nombre.", "danger")
        else:
            group = Group(name=name, description=description)
            db.session.add(group)
            db.session.commit()
            flash("Grupo creado correctamente.", "success")
            return redirect(url_for("admin_groups"))
    return render_template("admin_add_group.html")

@app.route("/admin/groups/edit/<int:group_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_group(group_id):
    group = Group.query.get_or_404(group_id)
    if request.method == "POST":
        group.name = request.form["name"]
        group.description = request.form["description"]
        db.session.commit()
        flash("Grupo actualizado correctamente.", "success")
        return redirect(url_for("admin_groups"))
    return render_template("admin_edit_group.html", group=group)

@app.route("/admin/groups/delete/<int:group_id>", methods=["POST"])
@admin_required
def admin_delete_group(group_id):
    group = Group.query.get_or_404(group_id)
    db.session.delete(group)
    db.session.commit()
    flash("Grupo eliminado correctamente.", "info")
    return redirect(url_for("admin_groups"))

@app.route("/admin/grade_levels")
@admin_required
def admin_grade_levels():
    grades = GradeLevel.query.all()
    return render_template("admin_grade_levels.html", grades=grades)

@app.route("/admin/grade_levels/add", methods=["GET", "POST"])
@admin_required
def admin_add_grade_level():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        if not name:
            flash("El nombre es obligatorio.", "warning")
        elif GradeLevel.query.filter_by(name=name).first():
            flash("Ya existe un grado con ese nombre.", "danger")
        else:
            grade = GradeLevel(name=name, description=description)
            db.session.add(grade)
            db.session.commit()
            flash("Grado creado correctamente.", "success")
            return redirect(url_for("admin_grade_levels"))
    return render_template("admin_add_grade_level.html")

@app.route("/admin/grade_levels/edit/<int:grade_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_grade_level(grade_id):
    grade = GradeLevel.query.get_or_404(grade_id)
    if request.method == "POST":
        grade.name = request.form["name"]
        grade.description = request.form["description"]
        db.session.commit()
        flash("Grado actualizado correctamente.", "success")
        return redirect(url_for("admin_grade_levels"))
    return render_template("admin_edit_grade_level.html", grade=grade)

@app.route("/admin/grade_levels/delete/<int:grade_id>", methods=["POST"])
@admin_required
def admin_delete_grade_level(grade_id):
    grade = GradeLevel.query.get_or_404(grade_id)
    db.session.delete(grade)
    db.session.commit()
    flash("Grado eliminado correctamente.", "info")
    return redirect(url_for("admin_grade_levels"))

@app.route("/admin/subjects")
@admin_required
def admin_subjects():
    subjects = Subject.query.all()
    return render_template("admin_subjects.html", subjects=subjects)

@app.route("/admin/subjects/add", methods=["GET", "POST"])
@admin_required
def admin_add_subject():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        if not name:
            flash("El nombre es obligatorio.", "warning")
        elif Subject.query.filter_by(name=name).first():
            flash("Ya existe una materia con ese nombre.", "danger")
        else:
            subject = Subject(name=name, description=description)
            db.session.add(subject)
            db.session.commit()
            flash("Materia creada correctamente.", "success")
            return redirect(url_for("admin_subjects"))
    return render_template("admin_add_subject.html")

@app.route("/admin/subjects/edit/<int:subject_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    if request.method == "POST":
        subject.name = request.form["name"]
        subject.description = request.form["description"]
        db.session.commit()
        flash("Materia actualizada correctamente.", "success")
        return redirect(url_for("admin_subjects"))
    return render_template("admin_edit_subject.html", subject=subject)

@app.route("/admin/subjects/delete/<int:subject_id>", methods=["POST"])
@admin_required
def admin_delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    flash("Materia eliminada correctamente.", "info")
    return redirect(url_for("admin_subjects"))

@app.route("/tasks", methods=["GET", "POST"])
@login_required
def tasks():
    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        due_date_str = request.form["due_date"]
        if not title or not due_date_str:
            flash("El título y la fecha de vencimiento son obligatorios.", "warning")
        else:
            from models import Task
            # Convertir string a objeto date
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            task = Task(
                user_id=g.user.id,
                title=title,
                description=description,
                due_date=due_date
            )
            db.session.add(task)
            db.session.commit()
            flash("Tarea agregada correctamente.", "success")
            return redirect(url_for("tasks"))
    tasks = g.user.tasks
    return render_template("tasks.html", tasks=tasks)

@app.route("/tasks/complete/<int:task_id>", methods=["POST"])
@login_required
def complete_task(task_id):
    from models import Task
    task = Task.query.get_or_404(task_id)
    if task.user_id != g.user.id:
        abort(403)
    task.completed = True
    db.session.commit()
    flash("Tarea marcada como completada.", "success")
    return redirect(url_for("tasks"))

@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    from models import Task
    task = Task.query.get_or_404(task_id)
    if task.user_id != g.user.id:
        abort(403)
    db.session.delete(task)
    db.session.commit()
    flash("Tarea eliminada.", "info")
    return redirect(url_for("tasks"))

@app.route("/admin/grade_students", methods=["GET", "POST"])
@admin_required
def admin_grade_students():
    groups = Group.query.all()
    subjects = Subject.query.all()
    students = []
    selected_group = request.args.get("group_id")
    selected_subject = request.args.get("subject_id")
    if selected_group and selected_subject:
        group = Group.query.get(selected_group)
        subject = Subject.query.get(selected_subject)
        students = group.users
    if request.method == "POST":
        from models import Grade, StudentSubject
        for key, value in request.form.items():
            if key.startswith("grade_"):
                user_id = int(key.split("_")[1])
                if value.strip() == "":
                    continue  # No guardar si está vacío
                grade_value = float(value.replace(",", "."))  # Acepta punto o coma
                # Asignar la materia si no la tiene
                student_subject = StudentSubject.query.filter_by(user_id=user_id, subject_id=selected_subject).first()
                if not student_subject:
                    student_subject = StudentSubject(user_id=user_id, subject_id=selected_subject)
                    db.session.add(student_subject)
                # Guardar o actualizar calificación
                grade = Grade.query.filter_by(user_id=user_id, subject_id=selected_subject).first()
                if grade:
                    grade.grade_value = grade_value
                    grade.created_at = datetime.utcnow()
                else:
                    grade = Grade(user_id=user_id, subject_id=selected_subject, grade_value=grade_value)
                    db.session.add(grade)
        db.session.commit()
        flash("Calificaciones guardadas y materias asignadas automáticamente.", "success")
        return redirect(url_for("admin_grade_students", group_id=selected_group, subject_id=selected_subject))
    return render_template(
        "admin_grade_students.html",
        groups=groups,
        subjects=subjects,
        students=students,
        selected_group=selected_group,
        selected_subject=selected_subject
    )

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    from models import ClassSchedule, Subject
    subjects = Subject.query.all()
    if request.method == "POST":
        subject_id = request.form["subject_id"]
        day_of_week = int(request.form["day_of_week"])
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        teacher = request.form["teacher"]
        # Convertir a objetos time
        start_time_obj = datetime.strptime(start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(end_time, "%H:%M").time()
        cs = ClassSchedule(
            user_id=g.user.id,
            subject_id=subject_id,
            day_of_week=day_of_week,
            start_time=start_time_obj,
            end_time=end_time_obj,
            teacher=teacher
        )
        db.session.add(cs)
        db.session.commit()
        flash("Horario guardado correctamente.", "success")
        return redirect(url_for("schedule"))
    # Obtener horario del usuario
    schedule = g.user.class_schedules
    return render_template("schedule.html", schedule=schedule, subjects=subjects)

@app.route("/admin/schedule")
@admin_required
def admin_schedule():
    from models import ClassSchedule, User
    schedules = ClassSchedule.query.all()
    users = User.query.filter_by(is_admin=False).all()
    return render_template("admin_schedule.html", schedules=schedules, users=users)

@app.route("/admin/schedule/delete/<int:schedule_id>", methods=["POST"])
@admin_required
def admin_delete_schedule(schedule_id):
    from models import ClassSchedule
    schedule = ClassSchedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    flash("Horario eliminado correctamente.", "info")
    return redirect(url_for("admin_schedule"))

@app.route("/admin/reports")
@admin_required
def admin_reports():
    return render_template("admin_reports.html")

@app.route("/reports/grades")
@login_required
def report_grades():
    from models import Grade
    grades = Grade.query.filter_by(user_id=g.user.id).all()
    return render_template("report_grades.html", grades=grades)

@app.route("/reports/attendance")
@login_required
def report_attendance():
    return render_template("report_attendance.html")

@app.route("/reports/behavior")
@login_required
def report_behavior():
    return render_template("report_behavior.html")

@app.route("/admin/reports/grades")
@admin_required
def admin_report_grades():
    from models import Grade, User
    grades = Grade.query.all()
    users = User.query.filter_by(is_admin=False).all()
    return render_template("admin_report_grades.html", grades=grades, users=users)

@app.route("/admin/reports/attendance", methods=["GET", "POST"])
@admin_required
def admin_report_attendance():
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    selected_grade = request.args.get("grade_level")
    selected_group = request.args.get("group")
    query = Attendance.query.join(User)
    if selected_grade:
        query = query.filter(User.grade_level_id == selected_grade)
    if selected_group:
        query = query.filter(User.group_id == selected_group)
    attendances = query.order_by(Attendance.date.desc()).all()
    # Registrar nueva asistencia
    if request.method == "POST":
        user_id = request.form["user_id"]
        date = request.form["date"]
        present = request.form.get("present") == "on"
        # Evitar duplicados
        existing = Attendance.query.filter_by(user_id=user_id, date=date).first()
        if not existing:
            attendance = Attendance(user_id=user_id, date=date, present=present)
            db.session.add(attendance)
            db.session.commit()
            flash("Asistencia registrada.", "success")
        else:
            flash("Ya existe un registro para ese día.", "warning")
        return redirect(url_for("admin_report_attendance", grade_level=selected_grade, group=selected_group))
    return render_template("admin_report_attendance.html", attendances=attendances, grade_levels=grade_levels, groups=groups, selected_grade=selected_grade, selected_group=selected_group)

@app.route("/admin/reports/behavior", methods=["GET", "POST"])
@admin_required
def admin_report_behavior():
    grade_levels = GradeLevel.query.all()
    groups = Group.query.all()
    selected_grade = request.args.get("grade_level")
    selected_group = request.args.get("group")
    students = User.query.filter_by(is_admin=False)
    if selected_grade:
        students = students.filter_by(grade_level_id=selected_grade)
    if selected_group:
        students = students.filter_by(group_id=selected_group)
    students = students.all()
    if request.method == "POST":
        for student in students:
            desc = request.form.get(f"behavior_{student.id}")
            if desc:
                behavior = Behavior(user_id=student.id, description=desc)
                db.session.add(behavior)
        db.session.commit()
        flash("Conducta guardada.", "success")
        return redirect(url_for("admin_report_behavior", grade_level=selected_grade, group=selected_group))
    return render_template("admin_report_behavior.html", students=students, grade_levels=grade_levels, groups=groups, selected_grade=selected_grade, selected_group=selected_group)

@app.route("/attendance")
@login_required
def attendance():
    attendances = Attendance.query.filter_by(user_id=g.user.id).order_by(Attendance.date.desc()).all()
    return render_template("attendance.html", attendances=attendances)

@app.route("/behavior")
@login_required
def behavior():
    behaviors = Behavior.query.filter_by(user_id=g.user.id).order_by(Behavior.created_at.desc()).all()
    return render_template("behavior.html", behaviors=behaviors)

@app.route("/api/grades")
@login_required
def api_grades():
    grades = g.user.grades.all()
    result = []
    for grade in grades:
        result.append({
            "subject_id": grade.subject_id,
            "grade_value": grade.grade_value
        })
    return {"grades": result}

if __name__ == "__main__":
    app.run(debug=True)