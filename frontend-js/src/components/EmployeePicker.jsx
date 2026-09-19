import { useMemo, useState } from "react";
import client from "../api/client";
import Modal from "./Modal";
import SearchSelect from "./SearchSelect";

export default function EmployeePicker({
  label,
  employees,
  departments,
  value,
  onChange,
  onCreated,
}) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    employee_code: "",
    name: "",
    department_id: "",
  });
  const options = useMemo(
    () =>
      employees.map((employee) => ({
        value: employee.id,
        label: `${employee.employee_code || "No ID"} — ${employee.name} — ${employee.department_name || "No department"}`,
      })),
    [employees],
  );
  const normalized = query.trim().toLowerCase();
  const hasMatch =
    normalized &&
    options.some((option) => option.label.toLowerCase().includes(normalized));
  const generalDepartments = departments.filter(
    (department) =>
      !/\b(warehouse|procurement|purchas)/i.test(
        department.name?.trim() || "",
      ),
  );

  async function save() {
    setError("");
    if (
      !form.employee_code.trim() ||
      !form.name.trim() ||
      !form.department_id
    ) {
      return setError("Employee ID, full name, and department are required.");
    }
    try {
      const employee = (
        await client.post("/masters/general-employees/quick", {
          ...form,
          department_id: Number(form.department_id),
        })
      ).data;
      onCreated(employee);
      onChange(employee.id, employee);
      setAdding(false);
      setForm({ employee_code: "", name: "", department_id: "" });
      setQuery("");
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(
        requestError?.response?.data?.error ||
          (typeof detail === "string" ? detail : detail?.[0]?.msg) ||
          (requestError?.request
            ? "Employee API is unavailable. Confirm the Python API is running on port 8001."
            : "Unable to add employee"),
      );
    }
  }

  return (
    <div>
      <SearchSelect data-field={"value"}
        label={label}
        options={options}
        value={value}
        onChange={(id) => {
          const employee = employees.find(
            (item) => String(item.id) === String(id),
          );
          onChange(id, employee);
        }}
        onSearch={setQuery}
        placeholder="Search name, employee ID, or department"
      />
      {normalized && !hasMatch && (
        <button
          type="button"
          className="mt-1 text-xs font-semibold text-brand-600 hover:text-brand-800"
          onClick={() => {
            setForm({
              employee_code: "",
              name: query.trim(),
              department_id: "",
            });
            setError("");
            setAdding(true);
          }}
        >
          No matching employee — add to Company Employees
        </button>
      )}
      <p className="mt-1 text-xs text-slate-500">
        Duplicate names are identified by employee ID and department.
      </p>
      {adding && (
        <Modal title="Add company employee" onClose={() => setAdding(false)}>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="text-sm font-medium text-slate-700">
                Employee ID *
              </label>
              <input data-field={"employee_code"}
                className="input mt-1 w-full"
                value={form.employee_code}
                onChange={(event) =>
                  setForm({ ...form, employee_code: event.target.value })
                }
                placeholder="e.g. EMP-1042"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700">
                Full name *
              </label>
              <input data-field={"name"}
                className="input mt-1 w-full"
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
            </div>
            <div className="md:col-span-2">
              <SearchSelect data-field={"department_id"}
                label="Department *"
                options={generalDepartments.map((department) => ({
                  value: department.id,
                  label: department.name,
                }))}
                value={form.department_id}
                onChange={(departmentId) =>
                  setForm({ ...form, department_id: departmentId })
                }
                placeholder="Type to search departments..."
              />
            </div>
            {error && (
              <div data-error-message="true" role="alert" className="md:col-span-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {error}
              </div>
            )}
            <div className="md:col-span-2 flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setAdding(false)}
              >
                Cancel
              </button>
              <button type="button" className="btn-primary" onClick={save}>
                Add employee
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
