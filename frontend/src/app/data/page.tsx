import FoundryDataView from "@/components/FoundryDataView";

/** Standalone deep link to the Foundry mission-data view. The same view also
 *  renders inside the operator console "Data" tab. */
export default function DataPage() {
  return (
    <div className="min-h-screen bg-bg">
      <FoundryDataView />
    </div>
  );
}
