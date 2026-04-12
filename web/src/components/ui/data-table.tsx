import * as React from "react";
import { Table, TableBody, TableRow, TableCell } from "./table";

interface DataTableProps {
  children: React.ReactNode;
  count?: number;
  empty?: string;
  colSpan?: number;
}

export function DataTable({ children, count, empty, colSpan = 6 }: DataTableProps) {
  return (
    <div className="rounded-md border border-border overflow-hidden">
      <div className="overflow-x-auto">
        <Table>
          {children}
          {count === 0 && empty && (
            <TableBody>
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={colSpan}
                  className="h-24 text-center text-sm text-muted-foreground max-w-none"
                >
                  {empty}
                </TableCell>
              </TableRow>
            </TableBody>
          )}
        </Table>
      </div>
    </div>
  );
}
