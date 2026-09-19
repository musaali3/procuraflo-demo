import { useEffect, useState } from "react";
import client from "../../api/client";
import MasterDataPage from "./MasterDataPage";

export default function GeneralEmployeesPage() {
  const [departments, setDepartments] = useState([]);
  useEffect(() => {
    client
      .get("/masters/departments")
      .then((response) =>
        setDepartments(
          response.data.filter(
            (department) =>
              !/\b(warehouse|procurement|purchas)/i.test(
                department.name?.trim() || "",
              ),
          ),
        ),
      );
  }, []);
  return (
    <MasterDataPage
      title="Company Employees"
      description="Maintain non-procurement and non-warehouse personnel for requisitions, receipts, tools, and reporting."
      endpoint="/masters/general-employees"
      columns={[
        { key: "employee_code", label: "Employee ID (generated automatically)", readOnly: true },
        { key: "name", label: "Employee Name" },
        { key: "department_name", label: "Department" },
        { key: "position", label: "Position" },
        { key: "status", label: "Status" },
      ]}
      fields={[
        {
          key: "department_id",
          label: "Department",
          type: "searchselect",
          placeholder: "Type to search departments...",
          options: departments.map((department) => ({
            value: department.id,
            label: department.name,
          })),
        },
        { key: "employee_code", label: "Employee ID (generated automatically)", readOnly: true },
        { key: "name", label: "Full Name" },
        { key: "position", label: "Position / Job Title" },
        { key: "payroll_number", label: "Payroll Number" },
        { key: "email", label: "Email" },
        {
          key: "status",
          label: "Status",
          type: "select",
          options: [
            { value: "Active", label: "Active" },
            { value: "Inactive", label: "Inactive" },
          ],
        },
      ]}
      wideForm
    />
  );
}
