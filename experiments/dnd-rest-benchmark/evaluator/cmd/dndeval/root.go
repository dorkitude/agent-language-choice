package dndeval

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"dndeval/internal/eval"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"github.com/spf13/viper"
)

var rootCmd = &cobra.Command{
	Use:   "dndeval",
	Short: "Evaluate D&D REST engine benchmark implementations",
}

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "Run a benchmark suite against a target HTTP server",
	RunE: func(cmd *cobra.Command, args []string) error {
		timeout, err := time.ParseDuration(viper.GetString("timeout"))
		if err != nil {
			return fmt.Errorf("invalid timeout: %w", err)
		}

		config := eval.RunConfig{
			BaseURL:  viper.GetString("base_url"),
			Suite:    viper.GetString("suite"),
			Timeout:  timeout,
			FailFast: viper.GetBool("fail_fast"),
			Verbose:  viper.GetBool("verbose"),
		}
		report, err := eval.Run(cmd.Context(), config)
		if err != nil {
			return err
		}

		if jsonOut := viper.GetString("json_out"); jsonOut != "" {
			payload, err := json.MarshalIndent(report, "", "  ")
			if err != nil {
				return err
			}
			if err := os.WriteFile(jsonOut, append(payload, '\n'), 0o644); err != nil {
				return err
			}
		}

		fmt.Print(report.Text())
		if !report.Passed {
			return fmt.Errorf("suite failed: %d/%d tests passed", report.PassedCount, report.TotalCount)
		}
		return nil
	},
}

var listCmd = &cobra.Command{
	Use:   "list",
	Short: "List built-in benchmark suites",
	RunE: func(cmd *cobra.Command, args []string) error {
		for _, suite := range eval.Suites() {
			fmt.Fprintf(cmd.OutOrStdout(), "%s\t%s\t%d tests\n", suite.ID, suite.Name, len(suite.Tests))
		}
		return nil
	},
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

func init() {
	cobra.OnInitialize(initConfig)

	runCmd.Flags().String("base-url", "http://127.0.0.1:8080", "Target server base URL")
	runCmd.Flags().String("suite", "core", "Suite ID")
	runCmd.Flags().String("timeout", "3s", "Per-request timeout")
	runCmd.Flags().String("json-out", "", "Write JSON report to this path")
	runCmd.Flags().Bool("fail-fast", false, "Stop at first failed test")
	runCmd.Flags().BoolP("verbose", "v", false, "Show response details for passed tests")

	mustBind("base_url", runCmd.Flags().Lookup("base-url"))
	mustBind("suite", runCmd.Flags().Lookup("suite"))
	mustBind("timeout", runCmd.Flags().Lookup("timeout"))
	mustBind("json_out", runCmd.Flags().Lookup("json-out"))
	mustBind("fail_fast", runCmd.Flags().Lookup("fail-fast"))
	mustBind("verbose", runCmd.Flags().Lookup("verbose"))

	rootCmd.AddCommand(runCmd, listCmd)
}

func initConfig() {
	viper.SetEnvPrefix("DNDEVAL")
	viper.AutomaticEnv()
}

func mustBind(key string, flag *pflag.Flag) {
	if err := viper.BindPFlag(key, flag); err != nil {
		panic(err)
	}
}
